import json
import sys

from PyQt6.Qsci import QsciLexerJSON, QsciScintilla
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.json_data_store = {}  # Add a data store for JSON data
        self.currently_selected_item = None  # Track the currently selected tree item

    def init_ui(self):
        self.tree_widget = QTreeWidget()
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
        save_action.triggered.connect(self.save_json)
        file_menu.addAction(save_action)

        edit_menu = menubar.addMenu("Edit")
        self.toggle_search_action = QAction("Show/Hide Search and Replace", self)
        self.toggle_search_action.setShortcut("Ctrl+F")
        self.toggle_search_action.triggered.connect(
            self.search_replace_widget.toggle_visibility
        )
        edit_menu.addAction(self.toggle_search_action)

        insert_menu = menubar.addMenu("Insert")
        insert_nxlog = QAction("Insert NXlog", self)
        insert_nxlog.setShortcut("Ctrl+I")
        insert_nxlog.triggered.connect(self.insert_nxlog)
        insert_menu.addAction(insert_nxlog)

        format_menu = menubar.addMenu("Format")
        autoformat_action = QAction("Autoformat JSON", self)
        autoformat_action.setShortcut("Ctrl+P")
        autoformat_action.triggered.connect(self.autoformat_json)
        format_menu.addAction(autoformat_action)

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
            with open(file_name, "r") as file:
                data = json.load(file)
            self.tree_widget.clear()  # Clear existing items in the tree
            self.populate_tree(data, None)
            self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(0))

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

    def populate_tree(self, json_object, parent_item, parentData=None):
        if isinstance(json_object, dict):
            name = self._get_name(json_object)
            tree_item = (
                QTreeWidgetItem(parent_item, [name])
                if parent_item
                else QTreeWidgetItem(self.tree_widget, [name])
            )
            node_data = {
                "data": json_object,
                "parent": parentData,
                "treeItem": tree_item,
            }
            self.json_data_store[id(tree_item)] = node_data

            for child in json_object.get("children", []):
                self.populate_tree(child, tree_item, node_data)

        elif isinstance(json_object, list):
            for item in json_object:
                self.populate_tree(item, parent_item, parentData)

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
                raw_json = json.dumps(json_data, indent=4)
                self.json_editor.setText(raw_json)
            else:
                self.currently_selected_item = None

    def on_editor_text_changed(self):
        if self.currently_selected_item:
            try:
                updated_json = json.loads(self.json_editor.text())
                node_data = self.json_data_store[id(self.currently_selected_item)]
                node_data["data"] = updated_json
                new_name = self._get_name(updated_json)
                self.currently_selected_item.setText(0, new_name)

                # Clear current children of the tree item
                self.currently_selected_item.takeChildren()

                # Recursively add new children if they exist
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
                self.status_bar.showMessage(f"JSON Error: {e.msg} at line {e.lineno}, column {e.colno}")

        elif self.tree_widget.topLevelItemCount() == 0:
            try:
                updated_json = json.loads(self.json_editor.text())
                self.tree_widget.clear()  # Clear existing items in the tree
                self.populate_tree(updated_json, None)
                self.clear_error_highlighting()
                self.status_bar.showMessage("Looks good!")
            except json.JSONDecodeError as e:
                # Handle invalid JSON
                self.highlight_error(e.lineno, e.colno)
                self.status_bar.showMessage(f"JSON Error: {e.msg} at line {e.lineno}, column {e.colno}")

    def highlight_error(self, line, col):
        # Clear previous highlights
        self.clear_error_highlighting()
        # Convert line and column to position
        position = self.json_editor.positionFromLineIndex(line - 1, col - 1)
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

    def create_initial_json(self):
        return {
            "children": [
                {
                    "name": "entry",
                    "type": "group",
                    "attributes": [
                        {
                            "name": "NX_class",
                            "dtype": "string",
                            "values": "NXentry"
                        }
                    ],
                    "children": []
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
                    "config": {"source": source, "topic": topic, "dtype": "double"},
                    "attributes": []
                    if not units
                    else [{"name": "units", "dtype": "string", "values": units}],
                }
            ],
        }

        # Insert into the currently selected JSON item
        if self.currently_selected_item:
            node_data = self.json_data_store.get(id(self.currently_selected_item))
            if node_data:
                json_data = node_data["data"]
                if "children" not in json_data:
                    json_data["children"] = []
                json_data["children"].append(skeleton_module)
                self.json_editor.setText(json.dumps(json_data, indent=4))
                self.on_editor_text_changed()  # Update the editor and data store
        else:
            # If no item is selected, insert at the root level
            self.populate_tree(skeleton_module, None)
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

    def save_json(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Save JSON File", "", "JSON Files (*.json)"
        )
        if file_name:
            json_data = self.build_json()
            with open(file_name, "w") as file:
                json.dump(json_data, file, indent=2)

    def validate_json(self):
        # Function to validate JSON data in the editor
        pass


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


def main():
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
