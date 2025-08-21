from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import re

_logger = logging.getLogger(__name__)

class DeleteDynamicFieldWizard(models.TransientModel):
    _name = 'delete.dynamic.field.wizard'
    _description = 'Asistente para eliminar campos dinámicos'

    subtask_id = fields.Many2one(
        'subtask.board', 
        string='Subtarea',
        default=lambda self: self.env.context.get('default_subtask_id')
    )
    
    field_to_delete = fields.Many2one(
        'ir.model.fields',
        string="Campo a eliminar",
        required=True,
        domain="[('model', '=', 'subtask.board'), ('state', '=', 'manual'), ('name', 'like', 'x_%')]"
    )

    def action_delete_dynamic_field(self):
        if not self.field_to_delete:
            raise UserError(_("No se ha seleccionado ningún campo para eliminar."))

        field_name = self.field_to_delete.name
        field_id = self.field_to_delete.id

        try:
            # 1. Primero eliminar todas las vistas que usan este campo
            self._delete_field_views(field_name)

            # 2. Eliminar la columna de la base de datos
            self.env.cr.execute(f"ALTER TABLE subtask_board DROP COLUMN IF EXISTS {field_name}")
            _logger.info("✅ Columna %s eliminada de la base de datos", field_name)

            # 3. Eliminar el registro de ir.model.fields
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
                if 'subtask.board' in self.env.registry._field_defs:
                    del self.env.registry._field_defs['subtask.board']
                    _logger.info("✅ Definiciones de campos limpiadas")

        except Exception as e:
            _logger.warning("⚠️ Advertencia al limpiar cachés: %s", str(e))

    def _delete_field_views(self, field_name):
        """Elimina todas las vistas que hacen referencia al campo dinámico"""
        try:
            # Buscar la vista específica view_subtask_tree
            specific_view = self.env['ir.ui.view'].search([
                ('name', '=', 'view_subtask_tree'),
                ('model', '=', 'subtask.board')
            ], limit=1)
            
            views_to_delete = self.env['ir.ui.view']
            
            if specific_view and specific_view.arch and field_name in specific_view.arch:
                views_to_delete |= specific_view
                _logger.info("📋 Vista view_subtask_tree encontrada con campo %s", field_name)
            
            # Buscar todas las demás vistas que contengan el campo
            all_views = self.env['ir.ui.view'].search([
                ('model', '=', 'subtask.board'),
                ('id', '!=', specific_view.id if specific_view else False)
            ])
            
            for view in all_views:
                if view.arch and field_name in view.arch:
                    views_to_delete |= view
                    _logger.info("📋 Vista %s encontrada con campo %s", view.name, field_name)
            
            # También buscar vistas por nombre que coincidan con patrones dinámicos
            pattern_views = self.env['ir.ui.view'].search([
                ('name', 'ilike', f'%{field_name}%'),
                ('model', '=', 'subtask.board')
            ])
            views_to_delete |= pattern_views
            
            # Eliminar duplicados y verificar que existan
            views_to_delete = views_to_delete.filtered(lambda v: v.exists())
            
            view_count = len(views_to_delete)
            
            if views_to_delete:
                view_names = views_to_delete.mapped('name')
                # Crear backup del XML antes de eliminar (opcional para debugging)
                for view in views_to_delete:
                    _logger.debug("🔧 Eliminando vista: %s - XML: %s", view.name, view.arch)
                
                views_to_delete.unlink()
                _logger.info("✅ %d vistas eliminadas para el campo %s: %s", 
                            view_count, field_name, view_names)
            else:
                _logger.info("ℹ️ No se encontraron vistas que usen el campo %s", field_name)
                
        except Exception as e:
            _logger.error("❌ Error al eliminar vistas del campo %s: %s", field_name, str(e))
            raise UserError(_("Error al eliminar vistas del campo '%s': %s") % (field_name, str(e)))