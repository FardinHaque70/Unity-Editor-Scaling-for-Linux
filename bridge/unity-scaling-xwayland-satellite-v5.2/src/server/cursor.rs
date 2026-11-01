use super::*;
use hecs::World;
use wayland_client::protocol::wl_pointer::WlPointer as ClientPointer;
use wayland_protocols::wp::tablet::zv2::client::zwp_tablet_tool_v2::ZwpTabletToolV2;
use wayland_protocols::wp::viewporter::client::wp_viewport::WpViewport;

#[derive(Copy, Clone)]
pub(super) struct BufferDimensions {
    pub width: i32,
    pub height: i32,
}

#[derive(Copy, Clone)]
pub(super) struct AttachedBufferDimensions(pub Option<BufferDimensions>);

pub(super) struct SurfaceBufferScale(pub i32);
pub(super) struct CursorSurface;

#[derive(Copy, Clone)]
pub(super) struct CursorRequest {
    pub surface: Option<Entity>,
    pub serial: u32,
    pub hotspot_x: i32,
    pub hotspot_y: i32,
}

fn cursor_hotspot(value: i32, incoming_buffer_scale: i32, render_scale: i32) -> i32 {
    // XWayland's request is already in its own surface coordinates. Recover
    // buffer coordinates before mapping into our fixed-density cursor surface.
    (i64::from(value) * i64::from(incoming_buffer_scale) / i64::from(render_scale)) as i32
}

pub(super) fn update_cursor_viewport(world: &World, surface: Entity, render_scale: i32) {
    let viewport = world.get::<&WpViewport>(surface).unwrap();
    let dimensions = world.get::<&AttachedBufferDimensions>(surface).ok();
    if let Some(dimensions) = dimensions.as_deref().and_then(|dimensions| dimensions.0) {
        let width = (f64::from(dimensions.width) / f64::from(render_scale)).ceil() as i32;
        let height = (f64::from(dimensions.height) / f64::from(render_scale)).ceil() as i32;
        if width > 0 && height > 0 {
            // Destination is absolute surface size: incoming buffer_scale must
            // not be divided out again. This also supports odd-sized bitmaps.
            viewport.set_destination(width, height);
        }
    } else {
        viewport.set_destination(-1, -1);
    }
}

fn forward_cursor(
    world: &World,
    controller: Entity,
    request: CursorRequest,
    render_scale: i32,
    incoming_buffer_scale: Option<i32>,
) {
    let surface = request
        .surface
        .and_then(|surface| world.get::<&client::wl_surface::WlSurface>(surface).ok());
    let buffer_scale = incoming_buffer_scale.unwrap_or_else(|| {
        request
            .surface
            .and_then(|surface| {
                world
                    .get::<&SurfaceBufferScale>(surface)
                    .ok()
                    .map(|scale| scale.0)
            })
            .unwrap_or(1)
    });
    let x = cursor_hotspot(request.hotspot_x, buffer_scale, render_scale);
    let y = cursor_hotspot(request.hotspot_y, buffer_scale, render_scale);
    if let Ok(pointer) = world.get::<&ClientPointer>(controller) {
        pointer.set_cursor(request.serial, surface.as_deref(), x, y);
    } else if let Ok(tool) = world.get::<&ZwpTabletToolV2>(controller) {
        tool.set_cursor(request.serial, surface.as_deref(), x, y);
    }
}

pub(super) fn set_fixed_cursor(
    world: &mut World,
    controller: Entity,
    request: CursorRequest,
    render_scale: i32,
) {
    if let Some(surface) = request.surface {
        world.insert_one(surface, CursorSurface).unwrap();
        update_cursor_viewport(world, surface, render_scale);
    }
    world.insert_one(controller, request).unwrap();
    forward_cursor(world, controller, request, render_scale, None);
}

pub(super) fn refresh_cursor_hotspots(
    world: &World,
    surface: Entity,
    incoming_buffer_scale: i32,
    render_scale: i32,
) {
    for (controller, request) in world.query::<&CursorRequest>().iter() {
        if request.surface == Some(surface) {
            forward_cursor(
                world,
                controller,
                *request,
                render_scale,
                Some(incoming_buffer_scale),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::cursor_hotspot;

    #[test]
    fn cursor_hotspot_accounts_for_existing_buffer_scale() {
        assert_eq!(cursor_hotspot(24, 1, 2), 12);
        assert_eq!(cursor_hotspot(12, 2, 2), 12);
        assert_eq!(cursor_hotspot(12, 3, 3), 12);
        assert_eq!(cursor_hotspot(0, 1, 2), 0);
        assert_eq!(cursor_hotspot(-24, 1, 2), -12);
    }
}
