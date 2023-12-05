# nc-lite
Small GUI for editing JSON files. Lighter than the nexus-constructor for quick edits.

### Features

- Syntax Highlighting: The editor highlights different JSON elements (keys, strings, numbers, etc.) for better readability and easier editing.
- Tree View: Display JSON data in a structured tree format, allowing easy navigation and understanding of the JSON structure.
- Search and Replace: Quickly find and replace text within the JSON file.
- Real-Time JSON Validation: Automatically checks JSON syntax while typing and highlights errors, helping to catch mistakes early.
- Bracket Matching and Indentation Guides: Enhances code readability by matching brackets and visually indicating indentation levels.
- File Operations: Open, modify, and save JSON files.
- Insert NXlog: Special feature to insert a pre-defined NXlog JSON structure.

### Installation

- Clone the repository: 

`git clone [repo]`

- Install the dependencies:

 `pip install -r requirements.txt`

- Run the script:

`python nc-lite.py`

### Usage

#### Open an existing JSON file
- Starting the Application: Run the script to open the JSON editor interface. 
- Opening a JSON File: Go to File > Open... to open an existing JSON file. The file content will be displayed both in the text editor and the tree view.
- Editing JSON: Directly edit the JSON in the text editor. The changes will reflect in the tree view. Syntax errors will be highlighted in real-time.
- Searching and Replacing Text: Use the search and replace feature (toggle with Ctrl+F) to find and replace text within the JSON file.
- Saving a JSON File: Save your changes or save the file as a new JSON file using File > Save as....

#### Paste raw JSON

- Copy the JSON text to the clipboard.
- Go to editor and press Ctrl+V to paste the JSON text.

#### Start from scratch
- Creating a New JSON File: Start a new JSON file with a basic template using File > New.
- Inserting NXlog Structure: Use the Insert > Insert NXlog to add a predefined NXlog structure into your JSON.


