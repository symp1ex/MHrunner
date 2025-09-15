from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem,
    QComboBox, QLabel, QMessageBox, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
import json
import os
import logging

class AddConnectionDialog(QDialog):
    """Диалог для добавления нового подключения"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add connection")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Тип подключения
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Type:"))
        self.conn_type = QComboBox()
        self.conn_type.addItems(["Anydesk", "LiteManager"])
        type_layout.addWidget(self.conn_type)
        layout.addLayout(type_layout)

        # Имя подключения
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(25)
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        # ID подключения
        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("ID:       "))
        self.id_edit = QLineEdit()
        self.id_edit.setMaxLength(15)
        id_layout.addWidget(self.id_edit)
        layout.addLayout(id_layout)

        # Кнопки
        buttons_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(save_btn)
        buttons_layout.addWidget(cancel_btn)
        layout.addLayout(buttons_layout)

    def get_data(self):
        return {
            "type": self.conn_type.currentText(),
            "name": self.name_edit.text(),
            "id": self.id_edit.text()
        }


class NotebookWindow(QDialog):
    """Основное окно книжки подключений"""
    connection_selected = pyqtSignal(str)  # Сигнал для передачи ID в главное окно

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connection Book")
        self.setFixedWidth(320)
        self.setFixedHeight(450)
        self.notebook_path = "notebook.json"
        self.notebook_default = {"Anydesk": {}, "LiteManager": {}}
        self.connections = self.load_connections()
        self.setup_ui()
        self.populate_tree()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Поисковая строка и кнопка добавления
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search...")
        self.search_edit.textChanged.connect(self.filter_connections)
        add_btn = QPushButton("+")
        add_btn.clicked.connect(self.add_connection)
        search_layout.addWidget(self.search_edit)
        search_layout.addWidget(add_btn)
        layout.addLayout(search_layout)

        # Дерево подключений
        self.tree = QTreeWidget()
        self.tree.setIndentation(10)
        self.tree.setHeaderHidden(True)  # Скрываем заголовки
        self.tree.setColumnCount(2)  # Уменьшаем до 2 колонок: имя и ID
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.tree)

    def create_notebook(self):
        logging.info("Файл записной книжки не найден")
        try:
            with open(self.notebook_path, "w", encoding="utf-8") as file:
                json.dump(self.notebook_default, file, ensure_ascii=False, indent=4)
            logging.info("Был создан пустой файл записной книжки")
        except Exception:
            logging.error("Не удалось создать файл записной книжки", exc_info=True)

    def load_connections(self):
        if not os.path.exists(self.notebook_path):
            self.create_notebook()
            return self.notebook_default
        try:
            with open(self.notebook_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить книжку: {e}")
            self.create_notebook()
            return self.notebook_default

    def save_connections(self):
        try:
            with open(self.notebook_path, 'w') as f:
                json.dump(self.connections, f, indent=4)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить книжку: {e}")

    def populate_tree(self):
        self.tree.clear()

        # Создаем корневые элементы для каждого типа подключения
        for conn_type, connections in self.connections.items():
            # Создаем родительский элемент для типа подключения
            type_item = QTreeWidgetItem([conn_type, ""])
            self.tree.addTopLevelItem(type_item)

            # Добавляем дочерние элементы (подключения)
            for name, id_value in connections.items():
                # Форматируем строку подключения с отступом
                connection_item = QTreeWidgetItem([f"{name}:  ", str(id_value)])
                type_item.addChild(connection_item)

            # Разворачиваем родительский элемент по умолчанию
            type_item.setExpanded(True)

        # Подгоняем ширину колонок под содержимое
        for i in range(2):
            self.tree.resizeColumnToContents(i)

    def filter_connections(self):
        search_text = self.search_edit.text().lower()

        # Проходим по всем типам подключений (корневым элементам)
        for i in range(self.tree.topLevelItemCount()):
            type_item = self.tree.topLevelItem(i)
            show_type = False

            # Проверяем все дочерние элементы (подключения)
            for j in range(type_item.childCount()):
                child_item = type_item.child(j)
                # Проверяем, содержит ли подключение искомый текст
                show_connection = any(
                    search_text in child_item.text(col).lower()
                    for col in range(child_item.columnCount())
                )
                child_item.setHidden(not show_connection)
                show_type = show_type or show_connection

            # Показываем тип, если есть видимые подключения или поиск пустой
            type_item.setHidden(not (show_type or not search_text))

    def add_connection(self):
        dialog = AddConnectionDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not all([data["name"], data["id"]]):
                QMessageBox.warning(self, "Ошибка", "Все поля должны быть заполнены")
                return

            self.connections[data["type"]][data["name"]] = data["id"]
            self.save_connections()
            self.populate_tree()

    def on_item_double_clicked(self, item, column):
        # Проверяем, что это дочерний элемент (подключение), а не тип
        if item.parent():
            connection_id = item.text(1)  # ID теперь в колонке 1
            self.connection_selected.emit(connection_id)
            self.accept()

    def show_context_menu(self, position):
        item = self.tree.itemAt(position)
        if item and item.parent():  # Проверяем, что это подключение, а не тип
            menu = QMenu()
            edit_action = menu.addAction("Edit")
            delete_action = menu.addAction("Delete")

            action = menu.exec(self.tree.viewport().mapToGlobal(position))
            if action == edit_action:
                self.edit_connection(item)
            elif action == delete_action:
                self.delete_connection(item)

    def edit_connection(self, item):
        conn_type = item.parent().text(0)
        old_name = item.text(0).rstrip(':  ')
        old_id = item.text(1)

        dialog = AddConnectionDialog(self)
        dialog.conn_type.setCurrentText(conn_type)
        dialog.name_edit.setText(old_name)
        dialog.id_edit.setText(old_id)

        if dialog.exec():
            data = dialog.get_data()
            if not all([data["name"], data["id"]]):
                QMessageBox.warning(self, "Ошибка", "Все поля должны быть заполнены")
                return

            # Удаляем старое подключение
            del self.connections[conn_type][old_name]
            # Добавляем новое
            self.connections[data["type"]][data["name"]] = data["id"]
            self.save_connections()
            self.populate_tree()

    def delete_connection(self, item):
        conn_type = item.parent().text(0)
        name = item.text(0).rstrip(':  ')

        reply = QMessageBox.question(
            self,
            'Подтверждение',
            f'Вы уверены, что хотите удалить подключение "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            del self.connections[conn_type][name]
            self.save_connections()
            self.populate_tree()