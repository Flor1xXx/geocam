[app]
title = GeoCam
package.name = geocam
package.domain = org.example
source.dir = .
source.include_exts = py,png,jpg,kv,json
version = 1.0
requirements = python3,kivy==2.3.0,camera4kivy,gestures4kivy,plyer,pillow,requests,urllib3,idna,charset-normalizer,certifi,openssl
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/icon.png

android.permissions = CAMERA,INTERNET,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION
android.api = 33
android.minapi = 29
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
p4a.hook = camerax_provider/gradle_options.py

[buildozer]
log_level = 2
warn_on_root = 1
