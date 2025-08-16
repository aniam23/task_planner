from odoo import models, fields, api, _
from odoo.exceptions import UserError
import re
from lxml import etree
import logging

_logger = logging.getLogger(__name__)

class DynamicFieldWizard(models.TransientModel):
    _name = 'dynamic.field.wizard'
    _description = 'Asistente para crear campos dinámicos por grupo exclusivo'

    # Campos del wizard
    dynamic_field_name = fields.Char(string="Nombre Técnico", required=True)
    dynamic_field_label = fields.Char(string="Etiqueta Visible", required=True)
    field_info = fields.Text(string="Valor Inicial")
    dynamic_field_type = fields.Selection([
        ('char', 'Texto'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('boolean', 'Booleano'),
        ('selection', 'Selección')],
        string="Tipo de Campo",
        required=True
    )
    selection_options = fields.Text(
        string="Opciones de Selección",
        help="Formato: clave:valor\nuno por línea"
    )

    subtask_id = fields.Many2one(
        'subtask.board',
        string="Subtarea Relacionada",
        default=lambda self: self._default_subtask_id()
    )

    def _default_subtask_id(self):
        """Obtiene la subtarea del contexto"""
        return self.env.context.get('default_subtask_id')
    # Grupo específico para este campo
    task_board_id = fields.Many2one(
        'task.board',
        string="Grupo Destino",
        required=True,
        readonly=True,
        default=lambda self: self._default_task_board_id()
    )

    def _default_task_board_id(self):
        """Obtiene el grupo de la subtarea asociada"""
        subtask_id = self.env.context.get('default_subtask_id')
        if subtask_id:
            subtask = self.env['subtask.board'].browse(subtask_id)
            if not subtask.task_id:
                raise UserError(_("La subtarea no está asignada a ningún grupo"))
            return subtask.task_id.id
        return False

    def action_create_dynamic_field(self):
        self.ensure_one()
        if not self.subtask_id:
            raise UserError(_("¡Error! Debe seleccionar una subtarea primero"))
        
        # Validación de campos requeridos
        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise UserError(_("¡Error! El nombre técnico y tipo de campo son obligatorios"))
        
        # Pasa los valores del wizard al subtask
        self.subtask_id.write({
        'dynamic_field_name': self.dynamic_field_name,
        'dynamic_field_label': self.dynamic_field_label,
        'dynamic_field_type': self.dynamic_field_type,
        'selection_options': self.selection_options,
        'field_info': self.field_info  # Añade esta línea para guardar la información
    })
    
    # Llama al método en la subtarea
        return self.subtask_id.action_create_dynamic_field()