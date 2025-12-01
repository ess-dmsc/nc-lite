import json
import sys
import threading

import numpy as np
import vtk
from PyQt6.Qsci import QsciLexerJSON, QsciScintilla
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from depend_on import DependsOnReportDialog, DependsOnVerifier

MAX_TOTAL_LIST_LEN = 1_000_000


def traverse_json(json_obj, condition_fn, action_fn, path=[]) -> None:
    """
    Recursively traverse the JSON object applying a condition function
    at each node. If the condition is met, applies an action function.

    :param json_obj: The JSON object or part of it being traversed.
    :param condition_fn: A function that takes a node and returns True if the condition is met.
    :param action_fn: A function that performs an action on nodes that meet the condition.
    :param path: The current path to the node, used for tracking the node's location within the JSON.
    """
    if condition_fn(json_obj):
        action_fn(json_obj, path)

    if isinstance(json_obj, dict):
        for key, value in json_obj.items():
            traverse_json(value, condition_fn, action_fn, path + [key])
    elif isinstance(json_obj, list):
        for index, item in enumerate(json_obj):
            traverse_json(item, condition_fn, action_fn, path + [index])


def is_within_cumulative_length_limit(json_obj, max_total_list_len=1000):
    """
    Checks if the total length of all lists in the JSON object exceeds max_total_list_len.

    :param json_obj: The JSON object (dict or list) to be checked.
    :param max_total_list_len: Maximum total length of all lists combined.
    :return: True if total length of all lists does not exceed max_total_list_len, False otherwise.
    """
    return check_cumulative_length(json_obj, max_total_list_len)[0]


def check_cumulative_length(obj, max_len, current_len=0):
    """
    Helper function to recursively check the cumulative length of lists.

    :param obj: Current object (dict or list) being checked.
    :param max_len: Maximum allowed cumulative length of lists.
    :param current_len: Current cumulative length of lists encountered.
    :return: Tuple (bool, int) where bool indicates if cumulative length does not exceed max_len, and int is the current cumulative length.
    """
    if isinstance(obj, list):
        current_len += len(obj)
        if current_len > max_len:
            return False, current_len
        for item in obj:
            if isinstance(item, (dict, list)):
                valid, current_len = check_cumulative_length(item, max_len, current_len)
                if not valid:
                    return False, current_len
    elif isinstance(obj, dict):
        for value in obj.values():
            if isinstance(value, (dict, list)):
                valid, current_len = check_cumulative_length(
                    value, max_len, current_len
                )
                if not valid:
                    return False, current_len

    return True, current_len


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.json_data_store = {}  # Add a data store for JSON data
        self.currently_selected_item = None  # Track the currently selected tree item

    def init_ui(self):
        self.tree_widget = CustomTreeWidget(self)
        self.json_editor = QsciScintilla()
        self.setup_editor()

        # Create a container for the editor and search/replace widget
        self.editor_container = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_container)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_layout.setSpacing(0)

        # Add the search and replace widget to the container
        self.search_replace_widget = SearchReplaceWidget(self.json_editor)
        self.editor_layout.addWidget(self.search_replace_widget)

        # Add the JSON editor to the container
        self.editor_layout.addWidget(self.json_editor)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree_widget)
        splitter.addWidget(self.editor_container)  # Add the container to the splitter

        self.status_bar = self.statusBar()

        self.setCentralWidget(splitter)

        # Menu for loading and saving JSON
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        new_action = QAction("New", self)
        new_action.triggered.connect(self.new_json)
        file_menu.addAction(new_action)

        open_action = QAction("Open...", self)
        open_action.triggered.connect(self.load_json)
        file_menu.addAction(open_action)

        save_action = QAction("Save as...", self)
        save_action.triggered.connect(lambda: self.save_json(compress=False))
        file_menu.addAction(save_action)

        save_compressed_action = QAction("Save as compressed...", self)
        save_compressed_action.triggered.connect(lambda: self.save_json(compress=True))
        file_menu.addAction(save_compressed_action)

        edit_menu = menubar.addMenu("Edit")
        self.toggle_search_action = QAction("Show/Hide Search and Replace", self)
        self.toggle_search_action.setShortcut("Ctrl+F")
        self.toggle_search_action.triggered.connect(
            self.search_replace_widget.toggle_visibility
        )
        edit_menu.addAction(self.toggle_search_action)

        delete_action = QAction("Delete Selected Item", self)
        delete_action.setShortcut("Delete")
        delete_action.triggered.connect(self.delete_selected_item)
        edit_menu.addAction(delete_action)

        insert_menu = menubar.addMenu("Insert")
        insert_nxlog = QAction("Insert NXlog", self)
        insert_nxlog.setShortcut("Ctrl+I")
        insert_nxlog.triggered.connect(self.insert_nxlog)
        insert_menu.addAction(insert_nxlog)

        insert_string = QAction("Insert String", self)
        insert_string.triggered.connect(self.insert_string)
        insert_menu.addAction(insert_string)

        format_menu = menubar.addMenu("Format")
        autoformat_action = QAction("Autoformat JSON", self)
        autoformat_action.setShortcut("Ctrl+P")
        autoformat_action.triggered.connect(self.autoformat_json)
        format_menu.addAction(autoformat_action)

        autoformat_nxdisk_chopper_action = QAction(
            "Auto-format selected NXdisk_chopper", self
        )
        autoformat_nxdisk_chopper_action.triggered.connect(
            self.autoformat_nxdisk_chopper
        )
        format_menu.addAction(autoformat_nxdisk_chopper_action)

        autoformat_nxpositioner_action = QAction(
            "Auto-format selected NXpositioner", self
        )
        autoformat_nxpositioner_action.triggered.connect(self.autoformat_nxpositioner)
        format_menu.addAction(autoformat_nxpositioner_action)

        view_menu = menubar.addMenu("View")
        render_off_geometry_action = QAction("Render OFF Geometry", self)
        render_off_geometry_action.triggered.connect(self.render_off_geometry)
        view_menu.addAction(render_off_geometry_action)

        tools_menu = menubar.addMenu("Tools")
        verify_action = QAction("Verify depends_on", self)
        verify_action.setShortcut("Ctrl+D")
        verify_action.triggered.connect(self.verify_depends_on)
        tools_menu.addAction(verify_action)

        self.tree_widget.itemSelectionChanged.connect(self.on_item_selection_changed)
        self.json_editor.textChanged.connect(self.on_editor_text_changed)

        self.tree_widget.setStyleSheet(
            """
            QTreeWidget {
                selection-background-color: #528BFF; /* Adjust color as needed */
                selection-color: white; /* Adjust text color as needed */
            }
        """
        )

    def setup_editor(self):
        # Set up the JSON lexer for syntax highlighting
        lexer = QsciLexerJSON()
        lexer.setDefaultPaper(QColor("#1e1e1e"))  # Dark background
        lexer.setDefaultColor(QColor("#d4d4d4"))  # Light grey
        lexer.setColor(
            QColor("#9CDCFE"), QsciLexerJSON.Property
        )  # Property names (keys)
        lexer.setColor(QColor("#CE9178"), QsciLexerJSON.String)  # Strings
        lexer.setColor(QColor("#B5CEA8"), QsciLexerJSON.Number)  # Numbers
        lexer.setColor(
            QColor("#569CD6"), QsciLexerJSON.Keyword
        )  # Keywords (true, false, null)
        lexer.setColor(
            QColor("#608B4E"), QsciLexerJSON.Operator
        )  # Operators (:, {, }, [, ])

        self.json_editor.setLexer(lexer)
        self.json_editor.setCaretForegroundColor(QColor("#FFFFFF"))
        self.json_editor.setMargins(0)
        self.json_editor.setMarginWidth(0, 0)
        self.json_editor.setAutoIndent(True)

        # Set up bracket matching
        self.json_editor.setBraceMatching(QsciScintilla.BraceMatch.StrictBraceMatch)
        self.json_editor.setMatchedBraceBackgroundColor(QColor("#3c3c3c"))
        self.json_editor.setMatchedBraceForegroundColor(QColor("#dcdcdc"))

        # Set up unmatched brace appearance if desired
        self.json_editor.setUnmatchedBraceBackgroundColor(QColor("#3c3c3c"))
        self.json_editor.setUnmatchedBraceForegroundColor(QColor("#ff0000"))

        # Enable indentation guides
        self.json_editor.setIndentationGuides(True)
        self.json_editor.setIndentationWidth(4)
        self.json_editor.setTabWidth(4)
        self.json_editor.setTabIndents(True)
        self.json_editor.setIndentationsUseTabs(False)
        self.json_editor.setIndentationGuidesBackgroundColor(QColor("#3c3c3c"))
        self.json_editor.setIndentationGuidesForegroundColor(QColor("#818181"))

        self.error_indicator_number = 0

        # Set the error indicator style
        self.json_editor.indicatorDefine(
            QsciScintilla.IndicatorStyle.FullBoxIndicator, self.error_indicator_number
        )
        self.json_editor.setIndicatorForegroundColor(
            QColor(255, 0, 0, 100), self.error_indicator_number
        )  # Semi-transparent red

    def load_json(self):
        # Open a file dialog to select the JSON file
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Open JSON File", "", "JSON Files (*.json)"
        )
        if file_name:
            try:
                with open(file_name, "r") as file:
                    data = json.load(file)

                self.tree_widget.clear()
                self.json_data_store.clear()
                self.currently_selected_item = None

                self.populate_tree(data, None)
                if self.tree_widget.topLevelItemCount() > 0:
                    self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(0))

            except json.JSONDecodeError as e:
                # Handle invalid JSON
                with open(file_name, "r") as file:
                    raw_json = file.read()
                    self.json_editor.setText(raw_json)
                self.highlight_error(e.lineno, e.colno)
                self.status_bar.showMessage(
                    f"JSON Error: {e.msg} at line {e.lineno}, column {e.colno}"
                )

    def _get_name(self, json_object):
        name = json_object.get("name")  # Get the 'name' value
        if name is None:
            # If 'name' key doesn't exist, check in 'config'
            config = json_object.get("config")
            if config and "name" in config:
                name = config["name"]
            elif config and "topic" and "source" in config:
                name = config["topic"] + " " + config["source"]
            else:
                # If still no name, use a default name or skip
                name = "<Unnamed>"
        return name

    def populate_tree(self, json_object, parent_item, parent_data=None):
        if isinstance(json_object, dict):
            name = self._get_name(json_object)
            tree_item = (
                QTreeWidgetItem(parent_item, [name])
                if parent_item
                else QTreeWidgetItem(self.tree_widget, [name])
            )
            node_data = {
                "data": json_object,
                "parent": parent_data,
                "treeItem": tree_item,
            }
            self.json_data_store[id(tree_item)] = node_data

            for child in json_object.get("children", []):
                self.populate_tree(child, tree_item, node_data)

        elif isinstance(json_object, list):
            for item in json_object:
                self.populate_tree(item, parent_item, parent_data)

        else:
            QTreeWidgetItem(parent_item, [str(json_object)])

    def on_item_selection_changed(self):
        selected_items = self.tree_widget.selectedItems()
        if selected_items:
            self.currently_selected_item = selected_items[0]
            node_data = self.json_data_store.get(id(self.currently_selected_item))
            if node_data:
                # Extract only the JSON data for serialization
                json_data = node_data.get("data", {})

                safe_to_render = is_within_cumulative_length_limit(
                    json_data, MAX_TOTAL_LIST_LEN
                )
                if safe_to_render:
                    raw_json = json.dumps(json_data, indent=4)
                    self.json_editor.setText(raw_json)
                else:
                    self.status_bar.showMessage(
                        f"Display Error: Total length of lists exceeds {MAX_TOTAL_LIST_LEN}"
                    )
            else:
                print("No data found for the selected item")
                self.currently_selected_item = None

    def on_editor_text_changed(self):
        if self.currently_selected_item:
            try:
                updated_json = json.loads(self.json_editor.text())
                node_data = self.json_data_store[id(self.currently_selected_item)]
                node_data["data"] = updated_json

                if isinstance(updated_json, dict):
                    new_name = self._get_name(updated_json)
                elif isinstance(updated_json, str):
                    new_name = updated_json
                else:
                    raise ValueError("Invalid JSON type")
                self.currently_selected_item.setText(0, new_name)

                old_children = [
                    self.currently_selected_item.child(i)
                    for i in range(self.currently_selected_item.childCount())
                ]
                for ch in old_children:
                    self._remove_subtree_from_store(ch)

                # Clear current children of the tree item
                self.currently_selected_item.takeChildren()

                # Recursively add new children if they exist
                if isinstance(updated_json, dict):
                    for child in updated_json.get("children", []):
                        self._add_tree_item(child, self.currently_selected_item)

                # Update the entire JSON hierarchy
                self.update_parent_node(
                    node_data["parent"], self.currently_selected_item, updated_json
                )
                self.clear_error_highlighting()
                self.status_bar.showMessage("Looks good!")

            except json.JSONDecodeError as e:
                # Handle invalid JSON
                self.highlight_error(e.lineno, e.colno)
                self.status_bar.showMessage(
                    f"JSON Error: {e.msg} at line {e.lineno}, column {e.colno}"
                )

        elif self.tree_widget.topLevelItemCount() == 0:
            try:
                updated_json = json.loads(self.json_editor.text())
                self.tree_widget.clear()
                self.json_data_store.clear()
                self.currently_selected_item = None

                self.populate_tree(updated_json, None)
                if self.tree_widget.topLevelItemCount() > 0:
                    self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(0))

                self.clear_error_highlighting()
                self.status_bar.showMessage("Looks good!")
            except json.JSONDecodeError as e:
                self.highlight_error(e.lineno, e.colno)
                self.status_bar.showMessage(
                    f"JSON Error: {e.msg} at line {e.lineno}, column {e.colno}"
                )

    def highlight_error(self, line, col):
        # Clear previous highlights
        self.clear_error_highlighting()
        # Length of the line
        line_length = len(self.json_editor.text(line - 1))
        # Apply the indicator over the line
        self.json_editor.fillIndicatorRange(
            line - 1, 0, line - 1, line_length, self.error_indicator_number
        )

    def clear_error_highlighting(self):
        # Clear the entire range of the document
        self.json_editor.clearIndicatorRange(
            0, 0, self.json_editor.lines(), 0, self.error_indicator_number
        )

    def autoformat_json(self):
        try:
            # Parse the current text as JSON
            json_object = json.loads(self.json_editor.text())
            # Pretty print the JSON
            formatted_json = json.dumps(json_object, indent=4)
            # Set the formatted JSON back to the editor
            self.json_editor.setText(formatted_json)
        except json.JSONDecodeError as e:
            # Handle invalid JSON, maybe show an error message
            self.status_bar.showMessage(f"Invalid JSON: {e}")

    def _add_tree_item(self, json_object, parent_item):
        # Check if jsonObject is a dictionary
        if isinstance(json_object, dict):
            name = self._get_name(json_object)
            tree_item = QTreeWidgetItem(parent_item, [name])

            # Store the linked data structure
            node_data = {
                "data": json_object,
                "parent": self.json_data_store.get(id(parent_item)),
                "treeItem": tree_item,
            }
            self.json_data_store[id(tree_item)] = node_data

            # Recursively add children
            for child in json_object.get("children", []):
                self._add_tree_item(child, tree_item)
        else:
            # Handle non-dictionary jsonObject (e.g., string, number)
            tree_item = QTreeWidgetItem(parent_item, [str(json_object)])
            self.json_data_store[id(tree_item)] = {
                "data": json_object,
                "parent": self.json_data_store.get(id(parent_item)),
            }

    def update_parent_node(self, parent_data, child_item, child_json):
        if parent_data is None:
            return
        parent_json = parent_data["data"]
        children = parent_json.get("children", [])

        # Check and update the specific child in the parent's 'children' list
        found = False
        for i, child in enumerate(children):
            if "treeItem" in parent_data and id(parent_data["treeItem"].child(i)) == id(
                child_item
            ):
                children[i] = child_json
                found = True
                break

        # If the child was updated, propagate the change to the parent
        if found:
            parent_data["data"]["children"] = children
            self.update_parent_node(
                parent_data["parent"], parent_data["treeItem"], parent_json
            )

    def _remove_subtree_from_store(self, item):
        """
        Remove the given QTreeWidgetItem and all of its descendants
        from json_data_store to avoid keeping dead subtrees alive.
        """
        if item is None:
            return

        stack = [item]
        while stack:
            it = stack.pop()
            for i in range(it.childCount()):
                stack.append(it.child(i))
            self.json_data_store.pop(id(it), None)

    def delete_selected_item(self):
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            return  # No item is selected

        item_to_delete = selected_items[0]
        parent_item = item_to_delete.parent()

        self._remove_subtree_from_store(item_to_delete)

        if parent_item:
            index = parent_item.indexOfChild(item_to_delete)
            parent_item.removeChild(item_to_delete)

            # Update parent's data in json_data_store
            parent_data = self.json_data_store.get(id(parent_item))
            if parent_data and "children" in parent_data["data"]:
                del parent_data["data"]["children"][index]

            self.tree_widget.setCurrentItem(parent_item)
            self.currently_selected_item = parent_item

        else:
            index = self.tree_widget.indexOfTopLevelItem(item_to_delete)
            self.tree_widget.takeTopLevelItem(index)

            self.currently_selected_item = None
            self.json_editor.clear()

            if self.tree_widget.topLevelItemCount() > 0:
                self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(0))

    def verify_depends_on(self):
        """
        Walks the current JSON, finds all nodes with a 'depends_on' attribute,
        resolves each chain according to NXtransformations rules, and reports:
          - broken references
          - cycles
          - missing attributes (vector, depends_on)
          - non-unit or invalid vectors
          - invalid/unknown transformation_type
          - offset present without offset_units (warning)
        """
        data = self.build_json()
        if data is None:
            self.status_bar.showMessage("Nothing to verify.")
            return

        verifier = DependsOnVerifier(data)
        issues, summary = verifier.run()

        dlg = DependsOnReportDialog(self, issues, summary)
        dlg.exec()

        msg = (
            f"depends_on: {summary['chains_checked']} chain(s) checked, "
            f"{summary['errors']} error(s), {summary['warnings']} warning(s)"
        )
        self.status_bar.showMessage(msg)

    def insert_nxlog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Skeleton Module")
        layout = QFormLayout(dialog)

        # Create input fields
        name_edit = QLineEdit(dialog)
        module_edit = QLineEdit(dialog)
        source_edit = QLineEdit(dialog)
        topic_edit = QLineEdit(dialog)
        units_edit = QLineEdit(dialog)

        layout.addRow("Name:", name_edit)
        layout.addRow("Module:", module_edit)
        layout.addRow("Source:", source_edit)
        layout.addRow("Topic:", topic_edit)
        layout.addRow("Units:", units_edit)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.insert_nxlog_json(
                name_edit.text(),
                module_edit.text(),
                source_edit.text(),
                topic_edit.text(),
                units_edit.text(),
            )

    def insert_string(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Simple String")
        layout = QFormLayout(dialog)

        # Create input fields
        name_edit = QLineEdit(dialog)

        layout.addRow("Name:", name_edit)
        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.insert_simple_string(
                name_edit.text(),
            )

    def create_initial_json(self):
        return {
            "children": [
                {
                    "name": "entry",
                    "type": "group",
                    "attributes": [
                        {"name": "NX_class", "dtype": "string", "values": "NXentry"}
                    ],
                    "children": [],
                }
            ]
        }

    def new_json(self):
        # Clear the current JSON data store and tree widget
        self.json_data_store.clear()
        self.tree_widget.clear()
        self.currently_selected_item = None

        # Create initial JSON structure
        initial_json = self.create_initial_json()

        # Populate the tree and the editor with the initial JSON
        self.populate_tree(initial_json, None)
        # self.json_editor.setText(json.dumps(initial_json, indent=4))
        self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(0))

    def insert_nxlog_json(self, name, module, source, topic, units):
        # Construct the skeleton module JSON
        skeleton_module = {
            "name": name,
            "type": "group",
            "attributes": [{"name": "NX_class", "dtype": "string", "values": "NXlog"}],
            "children": [
                {
                    "module": module,
                    "config": {
                        "source": source,
                        "topic": topic,
                        "dtype": "double",
                        "value_units": units,
                    },
                    "attributes": (
                        []
                        if not units
                        else [{"name": "units", "dtype": "string", "values": units}]
                    ),
                }
            ],
        }

        # Insert into the currently selected JSON item
        if self.currently_selected_item:
            node_data = self.json_data_store.get(id(self.currently_selected_item))
            if not node_data:
                return

            json_data = node_data["data"]
            if "children" not in json_data:
                json_data["children"] = []
            json_data["children"].append(skeleton_module)

            self._add_tree_item(skeleton_module, self.currently_selected_item)

            self.update_parent_node(
                node_data["parent"], self.currently_selected_item, json_data
            )

            safe_to_render = is_within_cumulative_length_limit(
                json_data, MAX_TOTAL_LIST_LEN
            )
            if safe_to_render:
                self.json_editor.blockSignals(True)
                try:
                    self.json_editor.setText(json.dumps(json_data, indent=4))
                finally:
                    self.json_editor.blockSignals(False)
            else:
                self.status_bar.showMessage(
                    f"NXlog inserted, but JSON is too large to render "
                    f"(total list length exceeds {MAX_TOTAL_LIST_LEN})."
                )

        else:
            # If no item is selected, insert at the root level
            self.populate_tree(skeleton_module, None)
            self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(0))

    def insert_simple_string(self, name):
        if self.currently_selected_item:
            node_data = self.json_data_store.get(id(self.currently_selected_item))
            if not node_data:
                return

            json_data = node_data["data"]
            if "children" not in json_data:
                json_data["children"] = []
            json_data["children"].append(name)

            self._add_tree_item(name, self.currently_selected_item)

            self.update_parent_node(
                node_data["parent"], self.currently_selected_item, json_data
            )

            safe_to_render = is_within_cumulative_length_limit(
                json_data, MAX_TOTAL_LIST_LEN
            )
            if safe_to_render:
                self.json_editor.blockSignals(True)
                try:
                    self.json_editor.setText(json.dumps(json_data, indent=4))
                finally:
                    self.json_editor.blockSignals(False)
            else:
                self.status_bar.showMessage(
                    f"String inserted, but JSON is too large to render "
                    f"(total list length exceeds {MAX_TOTAL_LIST_LEN})."
                )

        else:
            self.populate_tree(name, None)
            self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(0))

    def build_json(self, tree_item=None):
        if tree_item is None:
            # If no specific tree item is provided, start from the root items
            json_list = [self.build_json(item) for item in self.get_root_items()]
            return json_list[0] if len(json_list) == 1 else json_list

        node_data = self.json_data_store.get(id(tree_item))
        if node_data is None:
            return None

        json_object = node_data["data"]

        if tree_item.childCount() > 0:
            json_object["children"] = [
                self.build_json(tree_item.child(i))
                for i in range(tree_item.childCount())
            ]

        return json_object

    def get_root_items(self):
        return [
            self.tree_widget.topLevelItem(i)
            for i in range(self.tree_widget.topLevelItemCount())
        ]

    def save_json(self, compress=False):
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Save JSON File", "", "JSON Files (*.json)"
        )
        if file_name:
            json_data = self.build_json()
            with open(file_name, "w") as file:
                if compress:
                    json.dump(
                        json_data, file, separators=(",", ":"), ensure_ascii=False
                    )
                else:
                    json.dump(json_data, file, indent=2)

    def validate_json(self):
        # Function to validate JSON data in the editor
        pass

    def _get_attribute(self, node, name):
        if not isinstance(node, dict):
            return None
        for attr in node.get("attributes", []):
            if attr.get("name") == name:
                return attr
        return None

    def _get_nx_class(self, node):
        attr = self._get_attribute(node, "NX_class")
        if attr is None:
            return None
        return attr.get("values")

    def _is_nxlog_group(self, node):
        if not isinstance(node, dict):
            return False
        if node.get("type") != "group":
            return False
        return self._get_nx_class(node) == "NXlog"

    def _is_dataset_node(self, node):
        return isinstance(node, dict) and node.get("module") == "dataset"

    def _is_depends_on_dataset(self, node):
        if not self._is_dataset_node(node):
            return False
        return node.get("config", {}).get("name") == "depends_on"

    def _order_children_nexus(self, new_nxlogs, existing_children):
        """
        Combine freshly built NXlog children with existing non-NXlog children
        and order them as:

          1. All NXlog groups in alphabetical order by group name.
          2. All *static* datasets (module == 'dataset' and name != 'depends_on')
             in alphabetical order by config.name.
          3. Any remaining non-NXlog / non-dataset children in their original order
             (e.g. 'transformations' groups).
          4. Finally the 'depends_on' dataset(s), in their original order.
        """

        static_datasets = []
        other_children = []
        depends_on_datasets = []

        for child in existing_children:
            if self._is_dataset_node(child):
                if self._is_depends_on_dataset(child):
                    depends_on_datasets.append(child)
                else:
                    static_datasets.append(child)
            else:
                other_children.append(child)

        nxlogs_sorted = sorted(new_nxlogs, key=lambda c: c.get("name", ""))
        static_sorted = sorted(
            static_datasets,
            key=lambda c: c.get("config", {}).get("name", ""),
        )

        return nxlogs_sorted + static_sorted + other_children + depends_on_datasets

    def _create_f144_nxlog_group(self, name, source, topic, dtype, units=None):
        """
        Helper to build a standard NXlog group with one f144 child.
        units:
          - pass a string (including "") to create 'value_units' and 'units' attribute
          - pass None to omit units
        """
        child = {
            "module": "f144",
            "config": {
                "source": source,
                "topic": topic,
                "dtype": dtype,
            },
        }

        if units is not None:
            child.setdefault("config", {})["value_units"] = units
            child["attributes"] = [
                {
                    "name": "units",
                    "dtype": "string",
                    "values": units,
                }
            ]

        group = {
            "name": name,
            "type": "group",
            "children": [child],
            "attributes": [
                {
                    "name": "NX_class",
                    "dtype": "string",
                    "values": "NXlog",
                }
            ],
        }
        return group

    def autoformat_nxdisk_chopper(self):
        if not self.currently_selected_item:
            self.status_bar.showMessage("No item selected.")
            return

        node_data = self.json_data_store.get(id(self.currently_selected_item))
        if not node_data:
            self.status_bar.showMessage("No data for selected item.")
            return

        group = node_data["data"]
        if not isinstance(group, dict):
            self.status_bar.showMessage("Selected node is not a group.")
            return

        if self._get_nx_class(group) != "NXdisk_chopper":
            self.status_bar.showMessage(
                "Selected group is not an NXdisk_chopper (NX_class != 'NXdisk_chopper')."
            )
            return

        params = self._prompt_nxdisk_chopper_params(group)
        if params is None:
            return
        pv_root, topic, tdc_suffix = params

        children = group.get("children", [])
        non_log_children = [c for c in children if not self._is_nxlog_group(c)]

        new_logs = self._build_nxdisk_chopper_logs(pv_root, topic, tdc_suffix)

        group["children"] = self._order_children_nexus(new_logs, non_log_children)

        self.json_editor.setText(json.dumps(group, indent=4))
        self.on_editor_text_changed()
        self.status_bar.showMessage("Auto-formatted NXdisk_chopper NXlogs.")

    def _prompt_nxdisk_chopper_params(self, group):
        """
        Dialog asking for chopper PV root, Kafka topic, and TDC suffix.

        Example:
          PV root:   ODIN-ChpSy1:Chop-FOC-101
          Topic:     odin_choppers
          TDC suffix (after ':'): 00-TS-I
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Auto-format NXdisk_chopper")
        layout = QFormLayout(dialog)

        pv_root_edit = QLineEdit(dialog)
        topic_edit = QLineEdit(dialog)
        tdc_suffix_edit = QLineEdit(dialog)

        tdc_suffix = "00-TS-I"

        tdc_found = False
        for child in group.get("children", []):
            if (
                isinstance(child, dict)
                and child.get("name") == "top_dead_center"
                and self._is_nxlog_group(child)
                and child.get("children")
            ):
                cfg = child["children"][0].get("config", {})
                src = cfg.get("source", "")
                topic = cfg.get("topic", "")
                if ":" in src:
                    parts = src.split(":")
                    pv_root_edit.setText(":".join(parts[:-1]))
                    tdc_suffix = parts[-1]
                if topic:
                    topic_edit.setText(topic)
                tdc_found = True
                break

        if not tdc_found:
            for child in group.get("children", []):
                if self._is_nxlog_group(child) and child.get("children"):
                    cfg = child["children"][0].get("config", {})
                    src = cfg.get("source", "")
                    topic = cfg.get("topic", "")
                    if ":" in src:
                        pv_root_edit.setText(":".join(src.split(":")[:-1]))
                    if topic:
                        topic_edit.setText(topic)
                    break

        tdc_suffix_edit.setText(tdc_suffix)

        layout.addRow("PV root:", pv_root_edit)
        layout.addRow("Topic:", topic_edit)
        layout.addRow("TDC suffix (after ':'):", tdc_suffix_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            pv_root = pv_root_edit.text().strip()
            topic = topic_edit.text().strip()
            tdc_suffix = tdc_suffix_edit.text().strip().lstrip(":")

            if not pv_root or not topic:
                self.status_bar.showMessage("PV root and topic must not be empty.")
                return None

            return pv_root, topic, tdc_suffix
        return None

    def _build_nxdisk_chopper_logs(self, pv_root, topic, tdc_suffix="02-TS-I"):
        """
        Build the canonical set of NXlog groups for an NXdisk_chopper.
        """
        logs = []

        # rotation_speed (Hz) :Spd_R
        logs.append(
            self._create_f144_nxlog_group(
                name="rotation_speed",
                source=f"{pv_root}:Spd_R",
                topic=topic,
                dtype="double",
                units="Hz",
            )
        )

        # rotation_speed_setpoint (Hz) :Spd_S
        logs.append(
            self._create_f144_nxlog_group(
                name="rotation_speed_setpoint",
                source=f"{pv_root}:Spd_S",
                topic=topic,
                dtype="double",
                units="Hz",
            )
        )

        # top_dead_center via tdct module, no dtype/units, NXlog group has default="time"
        tdc_source = f"{pv_root}:{tdc_suffix.lstrip(':')}"
        tdc_group = {
            "name": "top_dead_center",
            "type": "group",
            "children": [
                {
                    "module": "tdct",
                    "config": {
                        "topic": topic,
                        "source": tdc_source,
                    },
                }
            ],
            "attributes": [
                {
                    "name": "NX_class",
                    "dtype": "string",
                    "values": "NXlog",
                },
                {
                    "name": "default",
                    "dtype": "string",
                    "values": "time",
                },
            ],
        }
        logs.append(tdc_group)

        # delay (ns) :TotDly
        logs.append(
            self._create_f144_nxlog_group(
                name="delay",
                source=f"{pv_root}:TotDly",
                topic=topic,
                dtype="double",
                units="ns",
            )
        )

        # experiment_delay (ns) :ChopDly-S
        logs.append(
            self._create_f144_nxlog_group(
                name="experiment_delay",
                source=f"{pv_root}:ChopDly-S",
                topic=topic,
                dtype="double",
                units="ns",
            )
        )

        # mechanical_delay (degrees) :MechDly-S
        logs.append(
            self._create_f144_nxlog_group(
                name="mechanical_delay",
                source=f"{pv_root}:MechDly-S",
                topic=topic,
                dtype="double",
                units="degrees",
            )
        )

        # pulse_delay (ns) :BeamPosDly-S
        logs.append(
            self._create_f144_nxlog_group(
                name="pulse_delay",
                source=f"{pv_root}:BeamPosDly-S",
                topic=topic,
                dtype="double",
                units="ns",
            )
        )

        # park_angle (degrees) :Pos_R
        logs.append(
            self._create_f144_nxlog_group(
                name="park_angle",
                source=f"{pv_root}:Pos_R",
                topic=topic,
                dtype="double",
                units="degrees",
            )
        )

        return logs

    def autoformat_nxpositioner(self):
        if not self.currently_selected_item:
            self.status_bar.showMessage("No item selected.")
            return

        node_data = self.json_data_store.get(id(self.currently_selected_item))
        if not node_data:
            self.status_bar.showMessage("No data for selected item.")
            return

        group = node_data["data"]
        if not isinstance(group, dict):
            self.status_bar.showMessage("Selected node is not a group.")
            return

        if self._get_nx_class(group) != "NXpositioner":
            self.status_bar.showMessage(
                "Selected group is not an NXpositioner (NX_class != 'NXpositioner')."
            )
            return

        params = self._prompt_nxpositioner_params(group)
        if params is None:
            return
        pv_root, topic, units = params

        children = group.get("children", [])
        non_log_children = [c for c in children if not self._is_nxlog_group(c)]

        new_logs = self._build_nxpositioner_logs(pv_root, topic, units)

        group["children"] = self._order_children_nexus(new_logs, non_log_children)

        self.json_editor.setText(json.dumps(group, indent=4))
        self.on_editor_text_changed()
        self.status_bar.showMessage("Auto-formatted NXpositioner NXlogs.")

    def _prompt_nxpositioner_params(self, group):
        """
        Dialog asking for motor PV root, topic and units.

        Example:
          PV root:  ODIN-ColSl3:MC-SlYp-01:Mtr
          Topic:    odin_motion
          Units:    mm
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Auto-format NXpositioner")
        layout = QFormLayout(dialog)

        pv_root_edit = QLineEdit(dialog)
        topic_edit = QLineEdit(dialog)
        units_edit = QLineEdit(dialog)
        units_edit.setText("mm")

        for child in group.get("children", []):
            if self._is_nxlog_group(child) and child.get("children"):
                cfg = child["children"][0].get("config", {})
                src = cfg.get("source", "")
                topic = cfg.get("topic", "")
                value_units = cfg.get("value_units", "")

                if "." in src:
                    pv_root_edit.setText(src.rsplit(".", 1)[0])
                if topic:
                    topic_edit.setText(topic)
                if value_units:
                    units_edit.setText(value_units)
                break

        layout.addRow("PV root:", pv_root_edit)
        layout.addRow("Topic:", topic_edit)
        layout.addRow("Units (for value/target):", units_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            pv_root = pv_root_edit.text().strip()
            topic = topic_edit.text().strip()
            units = units_edit.text().strip()
            if not pv_root or not topic:
                self.status_bar.showMessage("PV root and topic must not be empty.")
                return None
            return pv_root, topic, units
        return None

    def _build_nxpositioner_logs(self, pv_root, topic, units):
        """
        Build the canonical NXlog groups for an NXpositioner.

        - value         -> pv_root + ".RBV"
        - target_value  -> pv_root + ".VAL"
        - idle_flag     -> pv_root + ".DMOV"  (int, units "")
        """
        logs = []

        # value
        logs.append(
            self._create_f144_nxlog_group(
                name="value",
                source=f"{pv_root}.RBV",
                topic=topic,
                dtype="double",
                units=units,
            )
        )

        # target_value
        logs.append(
            self._create_f144_nxlog_group(
                name="target_value",
                source=f"{pv_root}.VAL",
                topic=topic,
                dtype="double",
                units=units,
            )
        )

        # idle_flag (int, unitless but still represented as "")
        logs.append(
            self._create_f144_nxlog_group(
                name="idle_flag",
                source=f"{pv_root}.DMOV",
                topic=topic,
                dtype="int",
                units="",
            )
        )

        return logs

    def render_off_geometry(self):
        if not self.currently_selected_item:
            self.status_bar.showMessage("No item selected")
            return

        node_data = self.json_data_store.get(id(self.currently_selected_item))
        if not node_data:
            self.status_bar.showMessage("No data found for the selected item")
            return

        json_data = node_data["data"]
        geometries = self.get_off_geometries(json_data)
        if not geometries:
            self.status_bar.showMessage("No geometries found in the selected item")
            return

        actors = self.create_vtk_actors(geometries)

        self.show_vtk_window(actors)

    def get_off_geometries(self, json_obj):
        geometries = []

        def condition_fn(node):
            if (
                isinstance(node, dict)
                and "name" in node
                and node["name"] == "pixel_shape"
            ):
                if "children" not in node:
                    return False
                return True
            return False

        def action_fn(node, path):
            vertices = []
            faces = []
            winding_order = []
            for child in node["children"]:
                if child.get("config", {}).get("name") == "vertices":
                    vertices = child["config"]["values"]
                elif child.get("config", {}).get("name") == "faces":
                    faces = child["config"]["values"]
                elif child.get("config", {}).get("name") == "winding_order":
                    winding_order = child["config"]["values"]
            if vertices and faces and winding_order:
                geometries.append(
                    {
                        "vertices": vertices,
                        "faces": faces,
                        "winding_order": winding_order,
                    }
                )

        traverse_json(json_obj, condition_fn, action_fn)
        return geometries

    def create_vtk_actors(self, geometries):
        actors = []

        for geometry in geometries:
            vertices = np.array(geometry["vertices"])
            faces = np.array(geometry["faces"])
            winding_order = np.array(geometry["winding_order"])

            points = vtk.vtkPoints()
            for vertex in vertices:
                points.InsertNextPoint(vertex)

            polys = vtk.vtkCellArray()
            num_faces = len(faces)
            for i in range(num_faces):
                polys.InsertNextCell(4)
                polys.InsertCellPoint(winding_order[4 * i])
                polys.InsertCellPoint(winding_order[4 * i + 1])
                polys.InsertCellPoint(winding_order[4 * i + 2])
                polys.InsertCellPoint(winding_order[4 * i + 3])

            poly_data = vtk.vtkPolyData()
            poly_data.SetPoints(points)
            poly_data.SetPolys(polys)

            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly_data)

            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actors.append(actor)

        return actors

    def show_vtk_window(self, actors):
        class VTKWindow(QFrame):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.vtk_widget = QVTKRenderWindowInteractor(self)
                layout = QVBoxLayout()
                layout.addWidget(self.vtk_widget)
                self.setLayout(layout)

                self.renderer = vtk.vtkRenderer()
                for actor in actors:
                    self.renderer.AddActor(actor)
                self.renderer.SetBackground(0.1, 0.2, 0.4)

                self.render_window = self.vtk_widget.GetRenderWindow()
                self.render_window.AddRenderer(self.renderer)

                self.interactor = self.vtk_widget
                self.interactor.SetRenderWindow(self.render_window)

                style = vtk.vtkInteractorStyleTrackballCamera()
                self.interactor.SetInteractorStyle(style)

                self.interactor.Initialize()
                self.interactor.Start()

        def thread_window():
            self.vtk_window = VTKWindow()
            self.vtk_window.show()

        threading.Thread(target=thread_window, daemon=True).start()


class SearchReplaceWidget(QWidget):
    def __init__(self, editor):
        super().__init__(editor)  # Parent set to editor for overlay
        self.editor = editor
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        self.search_box = QHBoxLayout()
        self.search_button = QPushButton("Search", self)
        self.search_button.clicked.connect(self.search)
        self.search_box.addWidget(self.search_button)
        self.search_field = QLineEdit(self)
        self.search_field.returnPressed.connect(self.search)
        self.search_box.addWidget(self.search_field)

        self.replace_box = QHBoxLayout()
        self.replace_button = QPushButton("Replace", self)
        self.replace_button.clicked.connect(self.replace)
        self.replace_box.addWidget(self.replace_button)
        self.replace_field = QLineEdit(self)
        self.replace_field.returnPressed.connect(self.replace)
        self.replace_box.addWidget(self.replace_field)

        self.layout.addLayout(self.search_box)
        self.layout.addLayout(self.replace_box)

        self.hide()

    def search(self):
        text = self.search_field.text()
        if text:
            self.editor.findFirst(text, False, True, False, True)

    def replace(self):
        search_text = self.search_field.text()
        replace_text = self.replace_field.text()
        if search_text:
            self.editor.replace(replace_text)
            self.editor.findFirst(search_text, False, True, False, True)

    def showEvent(self, event):
        self.search_field.setFocus()  # Focus on the search field when shown

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()  # Hide on ESC key

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.search_field.setFocus()


class CustomTreeWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.parent().delete_selected_item()
        else:
            super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
