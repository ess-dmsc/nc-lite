from PyQt6.QtWidgets import (QDialog, QDialogButtonBox,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                              QLabel)


class DependsOnVerifier:
    """
    Resolves 'depends_on' according to NXtransformations:

    - '.' terminates a chain
    - absolute '/a/b/c'
    - relative paths 'dir/name' resolved relative to the group that CONTAINS
      the attribute specifying 'depends_on'
    - bare names 'phi' resolved as siblings in the enclosing group

    Also validates axis fields:
      - 'vector' present, length 3, non-zero, ~unit length
      - 'transformation_type' in {'rotation','translation'} if present
      - 'depends_on' present on axis nodes in the chain (except final '.')
      - 'offset' (if present) length 3; warn if offset_units missing
    """

    def __init__(self, json_root):
        self.root = json_root
        self.index = {}            # absolute_path -> node (dict)
        self.node_group = {}       # id(node) -> enclosing group absolute path
        self.group_paths = set()   # for quick parent checks

        # Build index (handles root being dict or list)
        if isinstance(self.root, list):
            for child in self.root:
                self._build_index(child, "")
        else:
            self._build_index(self.root, "")

    def run(self):
        issues = []
        chains_checked = 0
        errors = 0
        warnings = 0

        for path, node in self.index.items():
            # Case A: transformation nodes (field/group) that carry a 'depends_on' ATTRIBUTE
            dep_attr = self._get_attr(node, "depends_on")
            if isinstance(dep_attr, str):
                chains_checked += 1
                issues.extend(self._verify_chain_from(node, path, dep_attr))

            # Case B: NXsample/NXdetector/... datasets named 'depends_on' (chain head pointer)
            if isinstance(node, dict) and node.get("module") == "dataset":
                cfg = node.get("config") or {}
                if cfg.get("name") == "depends_on":
                    dep_val = cfg.get("values")
                    if isinstance(dep_val, str):
                        chains_checked += 1
                        issues.extend(self._verify_chain_from(node, path, dep_val))
                    else:
                        issues.append(self._err(path, "depends_on dataset must be a string path"))

        for it in issues:
            if it["severity"] == "ERROR":
                errors += 1
            elif it["severity"] == "WARN":
                warnings += 1

        summary = {
            "chains_checked": chains_checked,
            "errors": errors,
            "warnings": warnings,
        }
        return issues, summary


    def _build_index(self, node, current_group_path):
        # Handle lists
        if isinstance(node, list):
            for item in node:
                self._build_index(item, current_group_path)
            return

        if not isinstance(node, dict):
            return

        # Is this an NX group? (e.g. NXtransformations, NXlog)
        if node.get("type") == "group" and node.get("name"):
            gname = node["name"]
            gpath = self._join(current_group_path, gname)
            self.index[gpath] = node
            # enclosing group of this group is its parent path
            self.node_group[id(node)] = self._parent(gpath)
            self.group_paths.add(gpath)

            for child in node.get("children", []):
                self._build_index(child, gpath)
            return

        # Is this a dataset-like node? name is in config.name
        if node.get("module") == "dataset":
            cfg = node.get("config") or {}
            fname = cfg.get("name")
            if fname:
                fpath = self._join(current_group_path, fname)
                self.index[fpath] = node
                # enclosing group is current group path
                self.node_group[id(node)] = current_group_path or "/"
            # Dataset nodes rarely have NX children; still traverse children if present
            for child in node.get("children", []):
                self._build_index(child, current_group_path)
            return

        # Generic dict: DO NOT index things like "config" dicts.
        # Just traverse to find nested NX groups/datasets.
        for k, v in list(node.items()):
            # We still traverse into 'children' and other sub-dicts,
            # but we never index this generic dict itself.
            if isinstance(v, (dict, list)):
                self._build_index(v, current_group_path)

    def _nx_class(self, node):
        return self._get_attr(node, "NX_class")

    def _nxlog_has_f144_value_units(self, node):
        """
        Returns (True, value_units) if any child f144 has config.value_units set to a non-empty string.
        """
        for ch in node.get("children", []) or []:
            if isinstance(ch, dict) and ch.get("module") == "f144":
                cfg = ch.get("config") or {}
                vu = cfg.get("value_units")
                if isinstance(vu, str) and vu.strip():
                    return True, vu
        return False, None

    @staticmethod
    def _join(base, name):
        base = base or ""
        if not base:
            return f"/{name}"
        return f"{base.rstrip('/')}/{name}"

    @staticmethod
    def _parent(path):
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) <= 1:
            return "/"
        return "/" + "/".join(parts[:-1])

    @staticmethod
    def _get_attr(node, attr_name):
        attributes = node.get("attributes", [])
        if isinstance(attributes, list):
            for a in attributes:
                if a.get("name") == attr_name:
                    return a.get("values")
        elif isinstance(attributes, dict):
            if attributes.get("name") == attr_name:
                return attributes.get("values")
        else:
            print(f"Warning: unexpected attributes type {type(attributes)} in node {node}")
        return None

    @staticmethod
    def _parse_vec(val):
        if isinstance(val, (list, tuple)) and len(val) == 3:
            try:
                return [float(val[0]), float(val[1]), float(val[2])]
            except (TypeError, ValueError):
                return None
        if isinstance(val, str):
            parts = [p.strip() for p in val.split(",")]
            if len(parts) == 3:
                try:
                    return [float(parts[0]), float(parts[1]), float(parts[2])]
                except ValueError:
                    return None
        return None

    def _get_dataset_value(self, node):
        """
        If this is a dataset-like node (module=='dataset'), return config.values.
        Otherwise return None.
        """
        if isinstance(node, dict) and node.get("module") == "dataset":
            cfg = node.get("config") or {}
            return cfg.get("values")
        return None

    def _verify_chain_from(self, start_node, start_path, first_dep_value):
        issues = []
        chain = []
        seen = set()

        base_group = self.node_group.get(id(start_node), self._parent(start_path))
        dep_val = first_dep_value

        # sanity: dep_val must be str or '.'
        if not isinstance(dep_val, str):
            issues.append(self._err(start_path, "depends_on attribute must be a string"))
            return issues

        # Follow chain
        steps = 0
        while True:
            steps += 1
            if steps > 10_000:
                issues.append(self._err(start_path, "Chain too long (possible infinite loop)"))
                break

            if dep_val == ".":
                # success end
                break

            target_path = self._resolve_path(base_group, dep_val)
            if target_path is None:
                issues.append(self._err(
                    start_path,
                    f"Unresolved depends_on reference '{dep_val}' relative to '{base_group}'"
                ))
                break

            if target_path in seen:
                loop = " -> ".join(list(chain) + [target_path])
                issues.append(self._err(start_path, f"Cycle detected: {loop}"))
                break

            seen.add(target_path)
            chain.append(target_path)

            target_node = self.index.get(target_path)
            if not isinstance(target_node, dict):
                issues.append(self._err(start_path, f"Target '{target_path}' is not a JSON object"))
                break

            # Validate the axis field (as per NXtransformations)
            issues.extend(self._validate_axis_field(target_node, start_path, target_path))

            # Next hop
            nxt = self._get_attr(target_node, "depends_on")
            if nxt is None:
                issues.append(self._err(
                    start_path,
                    f"Node '{target_path}' in chain is missing 'depends_on' (should be '.' at the end)"
                ))
                break

            base_group = self.node_group.get(id(target_node), self._parent(target_path))
            dep_val = nxt

        # Optional: add an INFO line with the resolved chain
        if chain:
            issues.append(self._info(
                start_path, f"Chain: {start_path} -> " + " -> ".join(chain) + " -> ."
            ))

        return issues

    def _validate_axis_field(self, node, start_path, node_path):
        issues = []

        # vector: required for axis
        vec = self._parse_vec(self._get_attr(node, "vector"))
        if vec is None:
            issues.append(self._err(start_path, f"'{node_path}': missing or invalid 'vector' (need 3 numbers)"))
        else:
            # non-zero and ~unit length
            mag2 = vec[0]*vec[0] + vec[1]*vec[1] + vec[2]*vec[2]
            if mag2 == 0.0:
                issues.append(self._err(start_path, f"'{node_path}': vector must be non-zero"))
            else:
                mag = mag2 ** 0.5
                if abs(mag - 1.0) > 1e-6:
                    issues.append(self._warn(start_path, f"'{node_path}': vector not unit length (|v|={mag:.6f})"))

        # transformation_type: if present, must be valid
        ttype = self._get_attr(node, "transformation_type")
        if ttype is not None:
            if ttype not in ("rotation", "translation"):
                issues.append(self._err(start_path, f"'{node_path}': invalid transformation_type '{ttype}'"))
            else:
                units = self._get_attr(node, "units")
                if units is None:
                    # Special-case NXlog: look for f144.value_units instead of warning
                    if self._nx_class(node) == "NXlog":
                        ok, vu = self._nxlog_has_f144_value_units(node)
                        if ok:
                            issues.append(self._info(start_path, f"'{node_path}': units provided via f144.value_units='{vu}'"))
                        else:
                            issues.append(self._warn(start_path, f"'{node_path}': NXlog has no 'units' and no f144.value_units found"))
                    else:
                        issues.append(self._warn(start_path, f"'{node_path}': missing 'units' attribute"))


        # offset: if present, must be 3-vector; warn if offset_units missing
        off = self._parse_vec(self._get_attr(node, "offset"))
        if off is not None:
            if len(off) != 3:
                issues.append(self._err(start_path, f"'{node_path}': offset must have 3 components"))
            if self._get_attr(node, "offset_units") is None:
                issues.append(self._warn(start_path, f"'{node_path}': has 'offset' but no 'offset_units'"))

        return issues

    def _resolve_path(self, base_group_path, ref):
        if not isinstance(ref, str):
            return None
        if ref == ".":
            return None
        if ref.startswith("/"):
            return self._normalize(ref) if self._normalize(ref) in self.index else None

        # Relative to the ENCLOSING GROUP of the attribute
        raw = f"{base_group_path.rstrip('/')}/{ref}"
        norm = self._normalize(raw)
        return norm if norm in self.index else None

    @staticmethod
    def _normalize(p):
        parts = [seg for seg in p.split("/") if seg and seg != "."]
        return "/" + "/".join(parts)

    @staticmethod
    def _err(node_path, msg):
        return {"severity": "ERROR", "node": node_path, "detail": msg}

    @staticmethod
    def _warn(node_path, msg):
        return {"severity": "WARN", "node": node_path, "detail": msg}

    @staticmethod
    def _info(node_path, msg):
        return {"severity": "INFO", "node": node_path, "detail": msg}


class DependsOnReportDialog(QDialog):
    def __init__(self, parent, issues, summary):
        super().__init__(parent)
        self.setWindowTitle("depends_on Verification")
        self.resize(900, 500)

        layout = QVBoxLayout(self)

        header = QLabel(
            f"Chains checked: {summary['chains_checked']} • "
            f"Errors: {summary['errors']} • Warnings: {summary['warnings']}"
        )
        layout.addWidget(header)

        tree = QTreeWidget(self)
        tree.setHeaderLabels(["Severity", "Node (start of chain)", "Detail"])
        tree.setColumnWidth(0, 90)
        tree.setColumnWidth(1, 320)

        # Show errors and warnings first, then infos
        prio = {"ERROR": 0, "WARN": 1, "INFO": 2}
        for item in sorted(issues, key=lambda x: (prio.get(x["severity"], 9), x["node"], x["detail"])):
            QTreeWidgetItem(tree, [item["severity"], item["node"], item["detail"]])

        layout.addWidget(tree)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)
