use super::XState;
use log::warn;
use std::collections::HashMap;
use xcb::x;

impl XState {
    pub(crate) fn set_xsettings_owner(&self) {
        self.connection
            .send_and_check_request(&x::SetSelectionOwner {
                owner: self.settings.window,
                selection: self.atoms.xsettings,
                time: x::CURRENT_TIME,
            })
            .unwrap();
        let reply = self
            .connection
            .wait_for_reply(self.connection.send_request(&x::GetSelectionOwner {
                selection: self.atoms.xsettings,
            }))
            .unwrap();

        if reply.owner() != self.settings.window {
            warn!(
                "Could not get XSETTINGS selection (owned by {:?})",
                reply.owner()
            );
        }
    }

    pub(crate) fn update_global_scale(&mut self, scale: f64) {
        self.settings.set_scale(scale);
        self.connection
            .send_and_check_request(&x::ChangeProperty {
                window: self.settings.window,
                mode: x::PropMode::Replace,
                property: self.atoms.xsettings_settings,
                r#type: self.atoms.xsettings_settings,
                data: &self.settings.as_data(),
            })
            .unwrap();
        self.update_xft_dpi_resource(self.settings.xft_dpi());
        if let Some(cursor) = &self.settings.cursor {
            publish_cursor_resources(&self.connection, &self.atoms, self.root, cursor);
        }
    }
}

/// The DPI consider 1x scale by X11.
const DEFAULT_DPI: i32 = 96;
/// I don't know why, but the DPI related xsettings seem to
/// divide the DPI by 1024.
const DPI_SCALE_FACTOR: i32 = 1024;

const XFT_DPI: &str = "Xft/DPI";
const GDK_WINDOW_SCALE: &str = "Gdk/WindowScalingFactor";
const GDK_UNSCALED_DPI: &str = "Gdk/UnscaledDPI";
const GTK_CURSOR_THEME: &str = "Gtk/CursorThemeName";
const GTK_CURSOR_SIZE: &str = "Gtk/CursorThemeSize";

pub(super) struct Settings {
    window: x::Window,
    serial: u32,
    settings: HashMap<&'static str, Setting>,
    cursor: Option<CursorSettings>,
}

#[derive(Clone, Debug, PartialEq)]
enum SettingValue {
    Integer(i32),
    String(String),
}

struct Setting {
    value: SettingValue,
    last_change_serial: u32,
}

mod setting_type {
    pub const INTEGER: u8 = 0;
    pub const STRING: u8 = 1;
}

#[derive(Clone, Debug, PartialEq)]
struct CursorSettings {
    theme: Option<String>,
    size: Option<i32>,
}

impl CursorSettings {
    fn from_values(
        render_scale: Option<&str>,
        theme: Option<&str>,
        size: Option<&str>,
    ) -> Result<Option<Self>, &'static str> {
        let Some(render_scale) = render_scale else {
            // Cursor advertisement is opt-in with the fixed-render policy.
            return Ok(None);
        };
        if !render_scale
            .parse::<i32>()
            .is_ok_and(|r| (1..=4).contains(&r))
        {
            return Err("UNITY_SATELLITE_RENDER_SCALE must be an integer from 1 to 4");
        }
        let theme = theme
            .map(|name| {
                if name.is_empty() || name.chars().any(char::is_control) {
                    Err("XCURSOR_THEME must be a nonempty name without control characters")
                } else {
                    Ok(name.to_owned())
                }
            })
            .transpose()?;
        let size = size
            .map(|value| {
                value
                    .parse::<i32>()
                    .ok()
                    // GTK3 clamps Gtk/CursorThemeSize above 128, which would
                    // otherwise diverge from native Xlib's cursor size.
                    .filter(|size| (1..=128).contains(size))
                    .ok_or("XCURSOR_SIZE must be 1 to 128 X11 pixels for uniform GTK3 cursors")
            })
            .transpose()?;
        Ok((theme.is_some() || size.is_some()).then_some(Self { theme, size }))
    }

    fn from_environment() -> Option<Self> {
        let render_scale = std::env::var("UNITY_SATELLITE_RENDER_SCALE").ok();
        let theme = std::env::var("XCURSOR_THEME").ok();
        let size = std::env::var("XCURSOR_SIZE").ok();
        Self::from_values(render_scale.as_deref(), theme.as_deref(), size.as_deref())
            .unwrap_or_else(|message| panic!("{message}"))
    }
}

fn merge_cursor_resources(resources: &[u8], cursor: &CursorSettings) -> Vec<u8> {
    let mut replacements: Vec<(&[u8], String)> = Vec::new();
    if let Some(theme) = &cursor.theme {
        // A resource value may contain escaped backslashes but never a new line.
        replacements.push((b"Xcursor.theme", theme.replace('\\', "\\\\")));
    }
    if let Some(size) = cursor.size {
        replacements.push((b"Xcursor.size", size.to_string()));
    }
    let mut seen = vec![false; replacements.len()];
    let mut updated = Vec::with_capacity(resources.len() + 96);
    for line in resources.split_inclusive(|byte| *byte == b'\n') {
        let name = line
            .iter()
            .position(|byte| *byte == b':')
            .map(|separator| line[..separator].trim_ascii());
        if let Some(index) = replacements.iter().position(|(key, _)| Some(*key) == name) {
            if !seen[index] {
                updated.extend_from_slice(replacements[index].0);
                updated.extend_from_slice(b":\t");
                updated.extend_from_slice(replacements[index].1.as_bytes());
                updated.push(b'\n');
                seen[index] = true;
            }
        } else {
            updated.extend_from_slice(line);
        }
    }
    for (index, (name, value)) in replacements.iter().enumerate() {
        if !seen[index] {
            if !updated.is_empty() && !updated.ends_with(b"\n") {
                updated.push(b'\n');
            }
            updated.extend_from_slice(name);
            updated.extend_from_slice(b":\t");
            updated.extend_from_slice(value.as_bytes());
            updated.push(b'\n');
        }
    }
    updated
}

fn publish_cursor_resources(
    connection: &xcb::Connection,
    atoms: &super::Atoms,
    root: x::Window,
    cursor: &CursorSettings,
) {
    // This connection belongs to the isolated Xwayland server. Preserve unrelated
    // resources, including Xft.dpi, and never write the host desktop's database.
    let reply = connection
        .wait_for_reply(connection.send_request(&x::GetProperty {
            delete: false,
            window: root,
            property: atoms.resource_manager,
            r#type: x::ATOM_STRING,
            long_offset: 0,
            long_length: u32::MAX,
        }))
        .unwrap();
    let resources = match reply.r#type() {
        x::ATOM_NONE => &[],
        x::ATOM_STRING => reply.value::<u8>(),
        other => {
            warn!("RESOURCE_MANAGER has unexpected type {other:?}; cursor resources unchanged");
            return;
        }
    };
    connection
        .send_and_check_request(&x::ChangeProperty {
            window: root,
            mode: x::PropMode::Replace,
            property: atoms.resource_manager,
            r#type: x::ATOM_STRING,
            data: &merge_cursor_resources(resources, cursor),
        })
        .unwrap();
}

impl Settings {
    pub(super) fn new(connection: &xcb::Connection, atoms: &super::Atoms, root: x::Window) -> Self {
        let window = connection.generate_id();
        connection
            .send_and_check_request(&x::CreateWindow {
                wid: window,
                width: 1,
                height: 1,
                depth: 0,
                parent: root,
                x: 0,
                y: 0,
                border_width: 0,
                class: x::WindowClass::InputOnly,
                visual: x::COPY_FROM_PARENT,
                value_list: &[],
            })
            .expect("Couldn't create window for settings");

        let s = Self::with_cursor(window, CursorSettings::from_environment());

        connection
            .send_and_check_request(&x::ChangeProperty {
                window,
                mode: x::PropMode::Replace,
                property: atoms.xsettings_settings,
                r#type: atoms.xsettings_settings,
                data: &s.as_data(),
            })
            .unwrap();
        if let Some(cursor) = &s.cursor {
            publish_cursor_resources(connection, atoms, root, cursor);
        }

        s
    }

    fn with_cursor(window: x::Window, cursor: Option<CursorSettings>) -> Self {
        let mut s = Settings {
            window,
            serial: 0,
            cursor,
            settings: HashMap::from([
                (
                    XFT_DPI,
                    Setting {
                        value: SettingValue::Integer(DEFAULT_DPI * DPI_SCALE_FACTOR),
                        last_change_serial: 0,
                    },
                ),
                (
                    GDK_WINDOW_SCALE,
                    Setting {
                        value: SettingValue::Integer(1),
                        last_change_serial: 0,
                    },
                ),
                (
                    GDK_UNSCALED_DPI,
                    Setting {
                        value: SettingValue::Integer(DEFAULT_DPI * DPI_SCALE_FACTOR),
                        last_change_serial: 0,
                    },
                ),
            ]),
        };

        if let Some(cursor) = &s.cursor {
            if let Some(theme) = &cursor.theme {
                s.settings.insert(
                    GTK_CURSOR_THEME,
                    Setting {
                        value: SettingValue::String(theme.clone()),
                        last_change_serial: 0,
                    },
                );
            }
            if let Some(size) = cursor.size {
                // GTK3 and Xcursor both expect physical X11 pixels here, not
                // logical desktop points. The launcher supplies logical_size * R.
                s.settings.insert(
                    GTK_CURSOR_SIZE,
                    Setting {
                        value: SettingValue::Integer(size),
                        last_change_serial: 0,
                    },
                );
            }
        }
        s
    }

    fn as_data(&self) -> Vec<u8> {
        // https://specifications.freedesktop.org/xsettings-spec/0.5/#format

        let mut data = vec![
            // GTK seems to use this value for byte order from the X.h header,
            // so I assume I can use it too.
            x::ImageOrder::LsbFirst as u8,
            // unused
            0,
            0,
            0,
        ];

        data.extend_from_slice(&self.serial.to_le_bytes());
        data.extend_from_slice(&(self.settings.len() as u32).to_le_bytes());

        fn insert_with_padding(data: &[u8], out: &mut Vec<u8>) {
            out.extend_from_slice(data);
            // See https://x.org/releases/X11R7.7/doc/xproto/x11protocol.html#Syntactic_Conventions_b
            let num_padding_bytes = (4 - (data.len() % 4)) % 4;
            out.extend(std::iter::repeat_n(0, num_padding_bytes));
        }

        for (name, setting) in &self.settings {
            let value_type = match &setting.value {
                SettingValue::Integer(_) => setting_type::INTEGER,
                SettingValue::String(_) => setting_type::STRING,
            };
            data.extend_from_slice(&[value_type, 0]);
            data.extend_from_slice(&(name.len() as u16).to_le_bytes());
            insert_with_padding(name.as_bytes(), &mut data);
            data.extend_from_slice(&setting.last_change_serial.to_le_bytes());
            match &setting.value {
                SettingValue::Integer(value) => data.extend_from_slice(&value.to_le_bytes()),
                SettingValue::String(value) => {
                    data.extend_from_slice(&(value.len() as u32).to_le_bytes());
                    insert_with_padding(value.as_bytes(), &mut data);
                }
            }
        }

        data
    }

    fn set_scale(&mut self, scale: f64) {
        self.serial += 1;

        let scale = scale.max(1.0);
        let dpi = (scale * DEFAULT_DPI as f64 * DPI_SCALE_FACTOR as f64).round() as i32;
        let setting = Setting {
            value: SettingValue::Integer(dpi),
            last_change_serial: self.serial,
        };
        self.settings.entry(XFT_DPI).insert_entry(setting);
        // Gdk/WindowScalingFactor + Gdk/UnscaledDPI is identical to setting
        // GDK_SCALE = scale and then GDK_DPI_SCALE = 1 / scale.
        self.settings.entry(GDK_UNSCALED_DPI).insert_entry(Setting {
            value: SettingValue::Integer(dpi / scale as i32),
            last_change_serial: self.serial,
        });
        self.settings.entry(GDK_WINDOW_SCALE).insert_entry(Setting {
            value: SettingValue::Integer(scale as i32),
            last_change_serial: self.serial,
        });
    }

    fn xft_dpi(&self) -> i32 {
        let setting = self.settings.get(XFT_DPI).unwrap();
        let SettingValue::Integer(value) = setting.value else {
            unreachable!("Xft/DPI must be an integer")
        };
        (value as f64 / DPI_SCALE_FACTOR as f64).round() as i32
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xcb::XidNew;

    fn decode(data: &[u8]) -> (u32, HashMap<String, (u32, SettingValue)>) {
        fn word(data: &[u8], offset: &mut usize) -> u32 {
            let value = u32::from_le_bytes(data[*offset..*offset + 4].try_into().unwrap());
            *offset += 4;
            value
        }
        fn padded_string(data: &[u8], offset: &mut usize, length: usize) -> String {
            let value = String::from_utf8(data[*offset..*offset + length].to_vec()).unwrap();
            *offset += length;
            while *offset % 4 != 0 {
                assert_eq!(data[*offset], 0, "Nonzero Xsettings padding");
                *offset += 1;
            }
            value
        }
        assert_eq!(&data[..4], &[0, 0, 0, 0]);
        let mut offset = 4;
        let serial = word(data, &mut offset);
        let count = word(data, &mut offset);
        let mut values = HashMap::new();
        for _ in 0..count {
            let kind = data[offset];
            assert_eq!(data[offset + 1], 0);
            let length = u16::from_le_bytes(data[offset + 2..offset + 4].try_into().unwrap());
            offset += 4;
            let name = padded_string(data, &mut offset, length as usize);
            let changed = word(data, &mut offset);
            let value = match kind {
                setting_type::INTEGER => SettingValue::Integer(word(data, &mut offset) as i32),
                setting_type::STRING => {
                    let length = word(data, &mut offset) as usize;
                    SettingValue::String(padded_string(data, &mut offset, length))
                }
                other => panic!("Unexpected Xsettings type {other}"),
            };
            assert!(values.insert(name, (changed, value)).is_none());
        }
        assert_eq!(offset, data.len(), "Trailing or missing serialized bytes");
        (serial, values)
    }

    #[test]
    fn cursor_xsettings_strings_use_utf8_byte_lengths_and_zero_padding() {
        // Cover every padding length and a multibyte theme name.
        for theme in ["A", "AB", "ABC", "ABCD", "Aé", "Breeze_Light"] {
            let settings = Settings::with_cursor(
                x::Window::new(1),
                Some(CursorSettings {
                    theme: Some(theme.to_owned()),
                    size: Some(72),
                }),
            );
            let (serial, values) = decode(&settings.as_data());
            assert_eq!(serial, 0);
            assert_eq!(values.len(), 5);
            assert_eq!(
                values[GTK_CURSOR_THEME],
                (0, SettingValue::String(theme.to_owned()))
            );
            assert_eq!(values[GTK_CURSOR_SIZE], (0, SettingValue::Integer(72)));
        }
    }

    #[test]
    fn cursor_configuration_is_only_enabled_by_valid_fixed_render_policy() {
        assert_eq!(
            CursorSettings::from_values(None, Some("\n"), Some("bad")),
            Ok(None)
        );
        assert_eq!(CursorSettings::from_values(Some("2"), None, None), Ok(None));
        assert_eq!(
            CursorSettings::from_values(Some("2"), Some("Breeze_Light"), Some("72")),
            Ok(Some(CursorSettings {
                theme: Some("Breeze_Light".into()),
                size: Some(72)
            }))
        );
        assert_eq!(
            CursorSettings::from_values(Some("3"), None, Some("108")),
            Ok(Some(CursorSettings {
                theme: None,
                size: Some(108)
            }))
        );
        for scale in ["", "0", "-1", "1.5", "5", "NaN"] {
            assert!(
                CursorSettings::from_values(Some(scale), Some("Breeze_Light"), Some("72")).is_err()
            );
        }
        assert!(CursorSettings::from_values(Some("4"), None, Some("128")).is_ok());
        for size in ["", "0", "-1", "1.5", "129", "144", "1025", "bad"] {
            assert!(CursorSettings::from_values(Some("2"), None, Some(size)).is_err());
        }
        for theme in ["", "bad\nname", "bad\0name", "bad\tname"] {
            assert!(CursorSettings::from_values(Some("2"), Some(theme), Some("72")).is_err());
        }
    }

    #[test]
    fn default_xsettings_and_dpi_updates_keep_the_original_integer_contract() {
        let mut settings = Settings::with_cursor(x::Window::new(1), None);
        let (serial, values) = decode(&settings.as_data());
        assert_eq!(serial, 0);
        assert_eq!(values.len(), 3);
        assert_eq!(values[XFT_DPI], (0, SettingValue::Integer(96 * 1024)));
        assert_eq!(values[GDK_WINDOW_SCALE], (0, SettingValue::Integer(1)));
        assert_eq!(
            values[GDK_UNSCALED_DPI],
            (0, SettingValue::Integer(96 * 1024))
        );
        settings.set_scale(2.0);
        let (serial, values) = decode(&settings.as_data());
        assert_eq!(serial, 1);
        assert_eq!(values.len(), 3);
        assert_eq!(values[XFT_DPI], (1, SettingValue::Integer(192 * 1024)));
        assert_eq!(values[GDK_WINDOW_SCALE], (1, SettingValue::Integer(2)));
        assert_eq!(
            values[GDK_UNSCALED_DPI],
            (1, SettingValue::Integer(96 * 1024))
        );
        assert_eq!(settings.xft_dpi(), 192);
    }

    #[test]
    fn dpi_updates_preserve_cursor_theme_and_physical_size() {
        let cursor = CursorSettings {
            theme: Some("Breeze_Light".into()),
            size: Some(72),
        };
        let mut settings = Settings::with_cursor(x::Window::new(1), Some(cursor));
        settings.set_scale(2.0);
        let (_, values) = decode(&settings.as_data());
        assert_eq!(
            values[GTK_CURSOR_THEME],
            (0, SettingValue::String("Breeze_Light".into()))
        );
        assert_eq!(values[GTK_CURSOR_SIZE], (0, SettingValue::Integer(72)));
    }

    #[test]
    fn cursor_resource_merge_preserves_other_resources_and_replaces_duplicates() {
        let cursor = CursorSettings {
            theme: Some("Breeze_Light".into()),
            size: Some(72),
        };
        let original = b"! keep comment\nXft.dpi:\t192\nXcursor.size: 36\nXcursor.theme: Adwaita\nXcursor.size: 48\nOther.value: untouched";
        let merged = merge_cursor_resources(original, &cursor);
        assert_eq!(merged, b"! keep comment\nXft.dpi:\t192\nXcursor.size:\t72\nXcursor.theme:\tBreeze_Light\nOther.value: untouched");
        assert_eq!(merge_cursor_resources(&merged, &cursor), merged);
        let size_only = CursorSettings {
            theme: None,
            size: Some(72),
        };
        assert_eq!(
            merge_cursor_resources(b"Xcursor.theme: keep", &size_only),
            b"Xcursor.theme: keep\nXcursor.size:\t72\n"
        );
        let escaped = CursorSettings {
            theme: Some("a\\b".into()),
            size: None,
        };
        assert_eq!(
            merge_cursor_resources(b"", &escaped),
            b"Xcursor.theme:\ta\\\\b\n"
        );
    }
}
