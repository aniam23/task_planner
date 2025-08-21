from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

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

    def action_delete_dynamic_field(self):
        if not self.field_to_delete:
            raise UserError(_("No se ha seleccionado ningún campo para eliminar."))

        field_name = self.field_to_delete.name

        try:
            # 1. Primero eliminar todas las vistas que usan este campo
            self._delete_field_views(field_name)

            # 2. Eliminar la columna de la base de datos
            self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
            _logger.info("✅ Columna %s eliminada de la base de datos", field_name)

            # 3. Eliminar el registro de ir.model.fields
            field_id = self.field_to_delete.id
            self.field_to_delete.unlink()
            _logger.info("✅ Registro %s eliminado de ir.model.fields", field_id)

            # 4. Limpiar cachés de forma segura
            self._safe_cache_clear()

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        except Exception as e:
            _logger.error("❌ Error eliminando campo %s: %s", field_name, str(e))
            raise UserError(_("Error al eliminar campo '%s': %s") % (field_name, str(e)))

    def _safe_cache_clear(self):
        """Limpieza segura de cachés sin recargar modelos"""
        try:
            # Métodos alternativos para limpiar cachés
            if hasattr(self.env.registry, 'clear_caches'):
                self.env.registry.clear_caches()
                _logger.info("✅ Cache del registry limpiado con clear_caches()")
            elif hasattr(self.env, 'clear_caches'):
                self.env.clear_caches()
                _logger.info("✅ Cache del environment limpiado")
            elif hasattr(self.env, 'invalidate_all'):
                self.env.invalidate_all()
                _logger.info("✅ Environment invalidado")

            # Limpiar cachés específicos de campos
            if hasattr(self.env.registry, '_field_defs'):
                if 'subtask.activity' in self.env.registry._field_defs:
                    del self.env.registry._field_defs['subtask.activity']
                    _logger.info("✅ Definiciones de campos limpiadas")

        except Exception as e:
            _logger.warning("⚠️ Advertencia al limpiar cachés: %s", str(e))

    def _delete_field_views(self, field_name):
        """Elimina solo las vistas específicas creadas para este campo dinámico"""
        try:
            # Buscar SOLO las vistas que creamos específicamente para este campo
            # con nuestros patrones de nombres predecibles
            exact_view_names = [
                f'subtask.activity.tree.dynamic.{field_name}.%',
                f'subtask.activity.form.dynamic.{field_name}.%'
            ]
            
            all_views = self.env['ir.ui.view']
            for pattern in exact_view_names:
                views = self.env['ir.ui.view'].search([
                    ('name', '=ilike', pattern),
                    ('model', '=', 'subtask.activity')
                ])
                all_views |= views
            
            # También buscar por el ID específico en el nombre de la vista (si lo tenemos)
            if hasattr(self, 'activity_id') and self.activity_id:
                activity_pattern = f'%.{self.activity_id.id}'
                activity_views = self.env['ir.ui.view'].search([
                    ('name', 'ilike', activity_pattern),
                    ('name', 'ilike', field_name),
                    ('model', '=', 'subtask.activity')
                ])
                all_views |= activity_views
            
            # Filtrar para asegurarnos de que solo eliminamos vistas de este campo específico
            all_views = all_views.filtered(
                lambda v: field_name in v.name and 'dynamic' in v.name
            )
            
            view_count = len(all_views)
            
            if all_views:
                view_names = all_views.mapped('name')
                all_views.unlink()
                _logger.info("✅ %d vistas eliminadas para el campo %s: %s", 
                            view_count, field_name, view_names)
            else:
                _logger.info("ℹ️ No se encontraron vistas específicas para eliminar del campo %s", field_name)
                
        except Exception as e:
            _logger.warning("⚠️ Error al eliminar vistas del campo %s: %s", field_name, str(e))