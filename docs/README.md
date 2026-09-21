# Z's Multi Tool — Module Development Guide

## 1. What is a module?

A module is a self-contained feature that Z's Multi Tool can discover and load.

The current module system uses a Python package/folder with an `__init__.py` file. The package calls `register(...)` and gives Z's Multi Tool the information it needs to display and open the module.

A typical module looks like:

```text
My Module/
├── __init__.py
└── ui.py
```

More complicated modules can have additional Python files, assets, folders, or dependencies.

---

## 2. The required registration file

Create:

```text
__init__.py
```

The current modules use a `register` function.

Example from the existing module format:

```python
def register(plugin_manager):
    plugin_manager.register({
        "name": "My Module",
        "category": "Utilities",
        "desc": "A short description of what my module does.",
        "icon": "🧰",
        "qt_page": "modules.My_Module.ui:MyModulePage",
    })
```

The important fields are:

- `name` — the marketplace/application display name.
- `category` — the category shown by the application.
- `desc` — a short description.
- `icon` — an emoji/icon used by the module listing.
- `qt_page` — the Python import path and class that should be opened.

---

## 3. Create the Qt page

The current application uses PySide6/Qt pages.

Example:

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class MyModulePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        title = QLabel("My Module")
        layout.addWidget(title)

        info = QLabel("Hello from my first Z's Multi Tool module!")
        layout.addWidget(info)
```

Save this as:

```text
ui.py
```

The class name must match the class named after the `:` in `qt_page`.

For the example above:

```text
qt_page = "modules.My_Module.ui:MyModulePage"
```

means:

```text
Python module: modules.My_Module.ui
Class:          MyModulePage
```

---

## 4. Folder structure

A simple module can look like:

```text
My_Module/
├── __init__.py
└── ui.py
```

A larger module can look like:

```text
My_Module/
├── __init__.py
├── ui.py
├── backend.py
├── helpers.py
├── assets/
│   └── icon.png
└── README.md
```

Keep the module self-contained whenever possible.

---

## 5. Complete starter example

### `__init__.py`

```python
def register(plugin_manager):
    plugin_manager.register({
        "name": "Hello Module",
        "category": "Utilities",
        "desc": "A simple example module for Z's Multi Tool.",
        "icon": "👋",
        "qt_page": "modules.Hello_Module.ui:HelloModulePage",
    })
```

### `ui.py`

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class HelloModulePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        title = QLabel("Hello Module")
        layout.addWidget(title)

        message = QLabel(
            "This is my first Z's Multi Tool module!"
        )
        layout.addWidget(message)
```

Folder:

```text
Hello_Module/
├── __init__.py
└── ui.py
```

---

## 6. Naming rules

Use a simple module/package name.

Good:

```text
QR_Tools
File_Organizer
My_Module
System_Stats
```

Avoid spaces and unusual characters in the Python package name.

The display name can still contain spaces:

```python
"name": "File Organizer"
```

while the folder/package can be:

```text
File_Organizer
```

---

## 7. Testing your module

Before submitting a module:

1. Put the module in the development `modules/` directory.
2. Start Z's Multi Tool.
3. Check that the module appears.
4. Open the module.
5. Test every button and feature.
6. Check that closing/reopening it works.
7. Test error cases.
8. Remove debug prints and temporary files.

If the module fails to load, check:

- `__init__.py` exists.
- `register(...)` exists.
- The registration dictionary is valid.
- `qt_page` points to the correct Python module and class.
- The class actually exists.
- Imports are correct.

---

## 8. Author information

When you submit your module through the marketplace submission system, you can choose the author name that should be shown publicly.

The author is the creator of the module.

The publisher is separate.

For example:

```text
My Module
By: JohnSmith
Published by: official
```

Your author name should not contain passwords, tokens, API keys, or other private information.

---

## 9. Preparing a submission

When your module is ready, use:

```text
Marketplace
→ Submit a Module
```

The submission system can collect your:

- author name
- module name
- description
- category
- module files

It then creates a submission package.

Do not put GitHub write tokens or other marketplace publishing credentials in your module.

---

## 10. Sending your submission

After the submission package is created, you can send it to the Z's Multi Tool developer.

The submission workflow provides options such as:

```text
Open Folder
Copy File Path
Open Email
Open Discord
Done
```

You can send the generated submission file by email, Discord, or another file-sharing method.

The submission package is for review. It does not give the module creator GitHub publishing access.

---

## 11. Review and publishing

Submitted modules are reviewed before they become official marketplace releases.

The developer can:

```text
Receive submission
       ↓
Inspect module
       ↓
Test module
       ↓
Check metadata
       ↓
Approve or reject
       ↓
Publish approved module
       ↓
Marketplace listing
```

Approval and publishing are developer-side operations.

---

## 12. What NOT to include

Never put these in a submitted module:

- GitHub write tokens
- marketplace credentials
- passwords
- private API keys
- personal secrets
- private certificates
- unrelated personal files

If your module needs an API key, design it so the user can enter/configure their own key locally.

---

## 13. Before submitting — checklist

### Module

- [ ] `__init__.py` exists
- [ ] `register(...)` is implemented
- [ ] `name` is set
- [ ] `category` is set
- [ ] `desc` is set
- [ ] `icon` is set
- [ ] `qt_page` is correct
- [ ] Qt page class exists
- [ ] Module loads successfully
- [ ] Module has been tested

### Submission

- [ ] Author name is correct
- [ ] Description is accurate
- [ ] No secrets are included
- [ ] No unnecessary files are included
- [ ] Submission package was created
- [ ] Submission was sent for review

---

## 14. Advanced modules

The simple example only uses `__init__.py` and `ui.py`.

Existing Z's Multi Tool modules can be much larger. The supplied module collection includes modules with multiple Python files, subpackages, backends, assets, and more.

Use the simple example as the starting point, then add files as your feature requires.

Do not copy large existing modules blindly. Start small and add one feature at a time.
