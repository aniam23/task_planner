from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import re

_logger = logging.getLogger(__name__)

class DeleteDynamicFieldWizard(models.TransientModel):
    _name = 'delete.field.subtask.wizard'
    _description = 'Wizard para eliminar campos dinámicos'

    activity_id = fields.Many2one('subtask.activity', string="Actividad", required=True)
    
    field_to_delete = fields.Many2one(
        'ir.model.fields',
        string="Campo a eliminar",
        required=True,
        domain="[('model','=','subtask.activity'),('state','=','manual'),('name','like','x_%')]"
    )

    def clean_specific_view_references(self, field_name):
        """Limpia referencias específicas en la vista subtask.planner.form"""
        try:
            # Buscar la vista específica
            specific_view = self.env['ir.ui.view'].search([
                ('name', '=', 'subtask.planner.form'),
                ('model', '=', 'subtask.board')
            ], limit=1)
            
            if specific_view:
                self._clean_field_from_view(specific_view, field_name)
                _logger.info("✅ Vista subtask.planner.form limpiada para el campo %s", field_name)
            else:
                _logger.warning("⚠️ Vista subtask.planner.form no encontrada")
                
        except Exception as e:
            _logger.error("❌ Error limpiando vista específica: %s", str(e))
    def action_delete_dynamic_field(self):
        self.ensure_one()
        if not self.field_to_delete:
            raise UserError(_("No se ha seleccionado ningún campo para eliminar."))

        field_name = self.field_to_delete.name

        try:
            # 1. PRIMERO eliminar TODAS las referencias en vistas
            self._delete_all_field_references(field_name)

            # 2. Eliminar el registro de ir.model.fields
            field_id = self.field_to_delete.id
            self.field_to_delete.unlink()
            _logger.info("✅ Registro %s eliminado de ir.model.fields", field_id)

            # 3. Eliminar la columna de la base de datos
            self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
            _logger.info("✅ Columna %s eliminada de la base de datos", field_name)

            # 4. Limpiar cachés de forma completa
            self._complete_cache_clear()

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        except Exception as e:
            _logger.error("❌ Error eliminando campo %s: %s", field_name, str(e))
            raise UserError(_("Error al eliminar campo '%s': %s") % (field_name, str(e)))

    def _delete_all_field_references(self, field_name):
        """Elimina TODAS las referencias a campos en vistas"""
        try:
            # Buscar en TODOS los modelos, no solo en subtask.activity
            all_views = self.env['ir.ui.view'].search([])
            views_to_clean = self.env['ir.ui.view']
            
            for view in all_views:
                try:
                    arch = view.arch_db or ''
                    if field_name in arch:
                        views_to_clean |= view
                        _logger.info("✅ Vista %s contiene el campo %s - Marcada para limpiar", view.name, field_name)
                except Exception as e:
                    _logger.warning("⚠️ Error revisando vista %s: %s", view.name, str(e))
                    continue
            
            # Limpiar referencias en las vistas encontradas
            for view in views_to_clean:
                self._clean_field_from_view(view, field_name)
                
        except Exception as e:
            _logger.error("❌ Error crítico al limpiar referencias: %s", str(e))
            raise UserError(_("Error al limpiar referencias del campo. Consulte los logs."))

    def _clean_field_from_view(self, view, field_name):
        """Elimina referencias a un campo específico de una vista"""
        try:
            arch = view.arch_db or ''
            
            # Patrones para buscar referencias al campo
            patterns = [
                f'name="{field_name}"',
                f'name=\'{field_name}\'',
                f'"{field_name}"',
                f"'{field_name}'"
            ]
            
            cleaned_arch = arch
            for pattern in patterns:
                # Eliminar campos completos que referencien al campo
                cleaned_arch = re.sub(
                    rf'<field[^>]*{pattern}[^>]*/>', 
                    '', 
                    cleaned_arch
                )
                
                # Eliminar atributos que contengan referencias al campo
                cleaned_arch = re.sub(
                    rf'(\s+[a-zA-Z_]+=["\'][^"\']*{pattern}[^"\']*["\'])', 
                    '', 
                    cleaned_arch
                )
            
            # Actualizar la vista solo si hubo cambios
            if cleaned_arch != arch:
                view.write({'arch_db': cleaned_arch})
                _logger.info("✅ Vista %s limpiada de referencias a %s", view.name, field_name)
                
        except Exception as e:
            _logger.error("❌ Error limpiando vista %s: %s", view.name, str(e))

    def _complete_cache_clear(self):
        """Limpieza completa de todos los cachés"""
        try:
            self.env.registry.clear_cache()
            self.env.invalidate_all()
            _logger.info("✅ Cachés limpiados completamente")
        except Exception as e:
            _logger.warning("⚠️ Advertencia al limpiar cachés: %s", str(e))

    @api.model
    def default_get(self, fields_list):
        """Establece valores por defecto"""
        result = super().default_get(fields_list)
        context = self.env.context
        
        if 'active_id' in context and context.get('active_model') == 'subtask.activity':
            result['activity_id'] = context['active_id']
        
        return result