from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class DeleteDynamicFieldWizard(models.TransientModel):
    _name = 'delete.dynamic.field.wizard'
    _description = 'Asistente para eliminar campos dinámicos'

    # Este campo ya no es necesario para la selección, pero lo dejamos por si acaso
    subtask_id = fields.Many2one(
        'subtask.board', 
        string='Subtarea',
        default=lambda self: self.env.context.get('active_id')
    )
    
    field_to_delete = fields.Many2one(
        'ir.model.fields',
        string="Campo a eliminar",
        required=True,
        domain="[('model', '=', 'subtask.activity'), ('state', '=', 'manual'), ('name', 'like', 'x_%')]"
    )

    @api.model
    def default_get(self, fields_list):
        """Cargar valores por defecto"""
        res = super(DeleteDynamicFieldWizard, self).default_get(fields_list)
        
        # Verificar que hay campos dinámicos disponibles
        dynamic_fields = self.env['ir.model.fields'].search([
            ('model', '=', 'subtask.activity'),
            ('state', '=', 'manual'),
            ('name', 'like', 'x_%')
        ])
        
        if not dynamic_fields:
            raise UserError(("No hay campos dinámicos disponibles para eliminar"))
        
        return res

    def action_delete_dynamic_field(self):
        """Elimina el campo dinámico seleccionado"""
        self.ensure_one()
        
        if not self.field_to_delete:
            raise UserError(("¡Error! Debe seleccionar un campo para eliminar"))
        
        field = self.field_to_delete
        field_name = field.name
        
        try:
            # 1. Eliminar la columna de la base de datos
            try:
                self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
                _logger.info("✅ Columna %s eliminada de BD", field_name)
            except Exception as e:
                _logger.warning("⚠️ No se pudo eliminar columna %s: %s", field_name, str(e))
            
            # 2. Eliminar vistas heredadas asociadas al campo
            views_to_delete = self.env['ir.ui.view'].search([
                ('model', '=', 'subtask.activity'),
                '|', 
                ('name', 'ilike', field_name),
                ('arch', 'ilike', field_name)
            ])
            
            if views_to_delete:
                views_to_delete.unlink()
                _logger.info("✅ %s vistas eliminadas para campo %s", len(views_to_delete), field_name)
            
            # 3. Eliminar el registro de ir.model.fields
            field.unlink()
            _logger.info("✅ Campo %s eliminado de ir.model.fields", field_name)
            
            # 4. Limpiar cachés
            self.env.registry.clear_cache()
            
            # 5. Mostrar mensaje de éxito
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': ('✅ Campo Eliminado'),
                    'message': (f'El campo "{field.field_description}" ({field_name}) ha sido eliminado exitosamente.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
            
        except Exception as e:
            _logger.error("❌ Error eliminando campo %s: %s", field_name, str(e))
            raise UserError(("Error al eliminar el campo: %s") % str(e))

    def action_show_all_dynamic_fields(self):
        """Muestra todos los campos dinámicos disponibles"""
        dynamic_fields = self.env['ir.model.fields'].search([
            ('model', '=', 'subtask.activity'),
            ('name', 'like', 'x_%'),
            ('state', '=', 'manual')
        ], order='field_description')
        
        if not dynamic_fields:
            raise UserError(("No hay campos dinámicos creados en el sistema"))
        
        # Crear mensaje con todos los campos
        field_list = "\n".join([f"• {field.field_description} ({field.name}) - {field.ttype}" 
                              for field in dynamic_fields])
        
        raise UserError(("Campos dinámicos disponibles:\n\n%s") % field_list)