#pragma once
#include <glib-object.h>
typedef GObject GtkWidget;
struct GtkAllocation {int x,y,width,height;};
#define GTK_IS_WIDGET(w) G_IS_OBJECT(w)
extern "C" gboolean gtk_widget_get_mapped(GtkWidget*);
