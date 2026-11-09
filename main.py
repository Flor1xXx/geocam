import json
import os
import shutil
import threading
import time

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.utils import platform

from camera4kivy import Preview  # noqa: F401  (регистрирует виджет в Factory)
from plyer import gps

from geo import reverse_geocode, haversine
from overlay import render_overlay, make_thumb, save_to_gallery, delete_from_gallery

KV = """
<Root>:
    CameraScreen:
    GalleryScreen:
    ViewScreen:

<CameraScreen>:
    name: 'camera'
    FloatLayout:
        Preview:
            id: preview
            aspect_ratio: '4:3'
        Label:
            text: app.info_text
            size_hint: 1, None
            text_size: self.width - dp(16), None
            height: self.texture_size[1] + dp(16)
            pos_hint: {'top': 1}
            halign: 'left'
            canvas.before:
                Color:
                    rgba: 0, 0, 0, .55
                Rectangle:
                    pos: self.pos
                    size: self.size
        Label:
            text: app.status
            size_hint: 1, None
            height: '32dp'
            y: dp(104)
        BoxLayout:
            size_hint: 1, None
            height: '96dp'
            padding: '12dp'
            spacing: '12dp'
            Button:
                text: 'Галерея'
                size_hint_x: .3
                on_release: app.open_gallery()
            Button:
                text: 'СНЯТЬ'
                font_size: '24sp'
                bold: True
                on_release: app.take_photo()

<GalleryItem>:
    size_hint_y: None
    height: '96dp'
    spacing: '8dp'
    padding: '4dp'
    AsyncImage:
        source: root.thumb
        size_hint_x: None
        width: '128dp'
        allow_stretch: True
    Label:
        text: root.caption
        text_size: self.size
        halign: 'left'
        valign: 'middle'
        shorten: True
        shorten_from: 'right'

<GalleryScreen>:
    name: 'gallery'
    BoxLayout:
        orientation: 'vertical'
        Button:
            text: '< Камера'
            size_hint_y: None
            height: '52dp'
            on_release: app.open_camera()
        ScrollView:
            GridLayout:
                id: grid
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                spacing: '4dp'

<ViewScreen>:
    name: 'view'
    BoxLayout:
        orientation: 'vertical'
        Image:
            id: img
            allow_stretch: True
        TextInput:
            id: txt
            size_hint_y: None
            height: '130dp'
            multiline: True
        BoxLayout:
            size_hint_y: None
            height: '52dp'
            Button:
                text: '< Назад'
                on_release: app.open_gallery()
            Button:
                text: 'Сохранить текст'
                on_release: app.save_edit(txt.text)
            Button:
                text: 'Удалить'
                on_release: app.delete_current()
"""


class Root(ScreenManager):
    pass


class CameraScreen(Screen):
    pass


class GalleryScreen(Screen):
    pass


class ViewScreen(Screen):
    pass


class GalleryItem(ButtonBehavior, BoxLayout):
    thumb = StringProperty()
    caption = StringProperty()
    pid = StringProperty()


class GeoCamApp(App):
    info_text = StringProperty("Ожидание GPS...")
    status = StringProperty("")

    def build(self):
        self.title = "GeoCam"
        self.last = None          # (lat, lon) последнего GPS-фикса
        self.address = None       # кэш адреса для geo_point
        self.geo_point = None
        self.geo_time = 0
        self.geo_busy = False
        self.cam_ready = False
        self.cam_on = False
        self.current_id = None
        self.dir = os.path.join(self.user_data_dir, "photos")
        os.makedirs(self.dir, exist_ok=True)
        Builder.load_string(KV)
        return Root(transition=NoTransition())

    # ---------- жизненный цикл / разрешения ----------
    def on_start(self):
        if platform == "android":
            from android.permissions import request_permissions, Permission
            request_permissions(
                [Permission.CAMERA, Permission.ACCESS_FINE_LOCATION,
                 Permission.ACCESS_COARSE_LOCATION], self.on_perms)
        else:  # тест на ПК: фейковая точка (Варшава)
            self.on_location(lat=52.2297, lon=21.0122)
            self.cam_ready = True
            self.connect_camera()

    def on_perms(self, perms, grants):
        if all(grants):
            self.cam_ready = True
            Clock.schedule_once(lambda dt: self.start_services())
        else:
            self.status = "Нужны разрешения на камеру и геолокацию"

    def start_services(self):
        self.connect_camera()
        try:
            gps.configure(on_location=self.on_location)
            gps.start(minTime=1000, minDistance=0)
        except NotImplementedError:
            self.info_text = "GPS недоступен на этом устройстве"

    def on_pause(self):
        self.disconnect_camera()
        return True

    def on_resume(self):
        if self.root.current == "camera":
            self.connect_camera()

    def on_stop(self):
        self.disconnect_camera()

    def connect_camera(self):
        if self.cam_ready and not self.cam_on:
            self.root.get_screen("camera").ids.preview.connect_camera()
            self.cam_on = True

    def disconnect_camera(self):
        if self.cam_on:
            self.root.get_screen("camera").ids.preview.disconnect_camera()
            self.cam_on = False

    # ---------- GPS + адрес ----------
    @mainthread
    def on_location(self, **kw):
        self.last = (kw["lat"], kw["lon"])
        self.refresh_info()
        self.maybe_geocode()

    def refresh_info(self):
        lat, lon = self.last
        text = f"Широта: {lat:.6f}  Долгота: {lon:.6f}"
        if self.address:
            text += "\n" + self.address
        self.info_text = text

    def maybe_geocode(self):
        if self.geo_busy or not self.last:
            return
        lat, lon = self.last
        age = time.time() - self.geo_time
        moved = (haversine(lat, lon, *self.geo_point) if self.geo_point else 1e9)
        if age < 8 or (moved < 15 and age < 60):
            return
        self.geo_busy = True
        threading.Thread(target=self._geo_job, args=(lat, lon), daemon=True).start()

    def _geo_job(self, lat, lon):
        self._geo_done(lat, lon, reverse_geocode(lat, lon))

    @mainthread
    def _geo_done(self, lat, lon, addr):
        self.geo_busy = False
        self.geo_time = time.time()
        if addr is not None:
            self.geo_point, self.address = (lat, lon), addr
            self.refresh_info()

    # ---------- съёмка ----------
    def take_photo(self):
        if not self.last:
            self.status = "Нет GPS-фикса, подождите..."
            return
        lat, lon = self.last
        addr = None
        if self.geo_point and haversine(lat, lon, *self.geo_point) < 25:
            addr = self.address
        pid = str(int(time.time() * 1000))
        self.status = "Снимаю..."
        self.root.get_screen("camera").ids.preview.capture_photo(
            location="private", subdir="orig", name=pid,
            filepath_callback=lambda path: threading.Thread(
                target=self.process, args=(pid, path, lat, lon, addr),
                daemon=True).start())

    def process(self, pid, path, lat, lon, addr):
        self.set_status("Обработка...")
        if addr is None:
            addr = reverse_geocode(lat, lon)
        text = f"Широта: {lat:.6f}  Долгота: {lon:.6f}\n"
        text += addr if addr else "(адрес недоступен — нет сети)"
        orig = os.path.join(self.dir, f"{pid}_orig.jpg")
        out = os.path.join(self.dir, f"{pid}.jpg")
        shutil.copy(path, orig)
        render_overlay(orig, out, text)
        make_thumb(out, os.path.join(self.dir, f"{pid}_t.jpg"))
        uri = save_to_gallery(out, f"GeoCam_{pid}.jpg")
        with open(os.path.join(self.dir, f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump({"lat": lat, "lon": lon, "text": text, "orig": orig,
                       "uri": uri}, f, ensure_ascii=False)
        self.set_status("Сохранено в галерею")

    @mainthread
    def set_status(self, s):
        self.status = s

    # ---------- галерея / редактирование ----------
    def open_camera(self):
        self.root.current = "camera"
        self.connect_camera()

    def open_gallery(self):
        self.disconnect_camera()
        grid = self.root.get_screen("gallery").ids.grid
        grid.clear_widgets()
        ids = sorted((f[:-5] for f in os.listdir(self.dir) if f.endswith(".json")),
                     reverse=True)
        for pid in ids:
            with open(os.path.join(self.dir, f"{pid}.json"), encoding="utf-8") as f:
                m = json.load(f)
            item = GalleryItem(thumb=os.path.join(self.dir, f"{pid}_t.jpg"),
                               caption=m["text"].replace("\n", "\n"), pid=pid)
            item.bind(on_release=lambda w: self.open_photo(w.pid))
            grid.add_widget(item)
        self.root.current = "gallery"

    def _meta(self, pid):
        with open(os.path.join(self.dir, f"{pid}.json"), encoding="utf-8") as f:
            return json.load(f)

    def open_photo(self, pid):
        self.current_id = pid
        m = self._meta(pid)
        s = self.root.get_screen("view")
        s.ids.img.source = os.path.join(self.dir, f"{pid}.jpg")
        s.ids.img.reload()
        s.ids.txt.text = m["text"]
        self.root.current = "view"

    def save_edit(self, new_text):
        pid = self.current_id
        m = self._meta(pid)
        m["text"] = new_text
        out = os.path.join(self.dir, f"{pid}.jpg")
        render_overlay(m["orig"], out, new_text)  # всегда с чистого оригинала
        make_thumb(out, os.path.join(self.dir, f"{pid}_t.jpg"))
        m["uri"] = save_to_gallery(out, f"GeoCam_{pid}.jpg", m.get("uri"))
        with open(os.path.join(self.dir, f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
        img = self.root.get_screen("view").ids.img
        img.source = out
        img.reload()

    def delete_current(self):
        pid = self.current_id
        m = self._meta(pid)
        delete_from_gallery(m.get("uri"))
        for suffix in (".json", ".jpg", "_t.jpg", "_orig.jpg"):
            try:
                os.remove(os.path.join(self.dir, pid + suffix))
            except OSError:
                pass
        self.open_gallery()


if __name__ == "__main__":
    GeoCamApp().run()
