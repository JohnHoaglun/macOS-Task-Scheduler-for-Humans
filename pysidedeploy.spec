[app]

# title of your application
title = macOS Task Scheduler for Humans

# project root directory. default = The parent directory of input_file
project_dir = .

# source file entry point path. default = main.py
input_file = src/task_scheduler/gui/app.py

# directory where the executable output is generated
exec_directory = dist

# path to the project file relative to project_dir
project_file = 

# application icon (empty = PySide6 fallback icon until an approved asset exists)
icon = /Users/johnhoaglun/opencode/projects/macOS Task Scheduler for Humans/.venv/lib/python3.14/site-packages/PySide6/scripts/deploy_lib/pyside_icon.icns

[python]

# python path
python_path = /Users/johnhoaglun/opencode/projects/macOS Task Scheduler for Humans/.venv/bin/python3.14

# python packages to install
packages = Nuitka==4.1.1

# buildozer = for deploying Android application
android_packages = buildozer==1.5.0,cython==0.29.33

[qt]

# paths to required qml files. comma separated
# normally all the qml files required by the project are added automatically
# design studio projects include the qml files using qt resources
qml_files = 

# excluded qml plugin binaries
excluded_qml_plugins = 

# qt modules used. comma separated
modules = Core,DBus,Gui,Widgets

# qt plugins used by the application. only relevant for desktop deployment
# for qt plugins used in android application see [android][plugins]
plugins = accessiblebridge,egldeviceintegrations,generic,iconengines,imageformats,platforminputcontexts,platforms,platforms/darwin,platformthemes,styles,wayland-decoration-client,wayland-graphics-integration-client,wayland-shell-integration,xcbglintegrations

[nuitka]

# usage description for permissions requested by the app as found in the info.plist file
# of the app bundle. comma separated
# eg = extra_args = --show-modules --follow-stdlib
macos.permissions = 

# mode of using nuitka. accepts standalone or onefile. default = onefile
mode = standalone

# specify any extra nuitka arguments
extra_args = --quiet --noinclude-qt-translations

