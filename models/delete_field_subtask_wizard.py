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
        self.ensure_one()
        if not self.field_to_delete:
            raise UserError(_("No se ha seleccionado ningún campo para eliminar."))

        field_name = self.field_to_delete.name

        try:
            # 1. PRIMERO eliminar TODAS las vistas que hacen referencia a este campo
            self._delete_all_field_views(field_name)

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

    def _delete_all_field_views(self, field_name):
        """Elimina TODAS las vistas que hacen referencia a este campo"""
        try:
            # Buscar TODAS las vistas que mencionan este campo en su arch XML
            all_views = self.env['ir.ui.view'].search([
                ('model', '=', 'subtask.activity')
            ])
            
            views_to_delete = self.env['ir.ui.view']
            
            for view in all_views:
                try:
                    # Verificar si el campo está mencionado en el archivo XML de la vista
                    if view.arch_db and field_name in view.arch_db:
                        views_to_delete |= view
                        _logger.info("✅ Vista %s contiene el campo %s - Marcada para eliminar", view.name, field_name)
                except Exception as e:
                    _logger.warning("⚠️ Error revisando vista %s: %s", view.name, str(e))
                    continue
            
            # También buscar vistas por nombre (patrones que usamos al crearlas)
            pattern_views = self.env['ir.ui.view'].search([
                ('model', '=', 'subtask.activity'),
                ('name', 'ilike', field_name)
            ])
            views_to_delete |= pattern_views
            
            # Eliminar duplicados
            views_to_delete = views_to_delete.filtered(lambda v: v.exists())
            
            if views_to_delete:
                view_names = views_to_delete.mapped('name')
                views_to_delete.unlink()
                _logger.info("✅ %d vistas eliminadas para el campo %s: %s", 
                            len(views_to_delete), field_name, view_names)
            else:
                _logger.info("ℹ️ No se encontraron vistas para eliminar del campo %s", field_name)
                
        except Exception as e:
            _logger.error("❌ Error crítico al eliminar vistas: %s", str(e))
            # Si falla la eliminación de vistas, no podemos continuar
            raise UserError(_("Error al eliminar vistas del campo. Consulte los logs."))

    def _complete_cache_clear(self):
        """Limpieza completa de todos los cachés"""
        try:
            # Método 1: Limpiar registry cache
            if hasattr(self.env.registry, '_clear_cache'):
                self.env.registry._clear_cache()
            
            # Método 2: Invalidar todo el environment
            self.env.invalidate_all()
            
            # Método 3: Limpiar cachés de vistas específicamente
            if hasattr(self.env['ir.ui.view'], 'clear_caches'):
                self.env['ir.ui.view'].clear_caches()
            
            # Método 4: Forzar recarga del modelo
            if hasattr(self.env.registry, 'setup_models'):
                self.env.registry.setup_models(self.env.cr, ['subtask.activity'])
            
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