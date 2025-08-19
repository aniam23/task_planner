from odoo import models, fields, api, tools
from odoo.exceptions import ValidationError, UserError
import logging
import re
from lxml import etree

_logger = logging.getLogger(__name__)

class SubtaskActivity(models.Model):
    _name = 'subtask.activity'
    _description = 'Actividad Interna de Subtarea'
    _inherit = ['mail.activity.mixin']
    
    name = fields.Char(string='Subtarea', required=True)
    date_deadline = fields.Date(string='Fecha')
    done = fields.Boolean(string='Completado')
    subtask_id = fields.Many2one('subtask.board', string='Subtarea', ondelete='cascade', required=True)
    person = fields.Many2one('hr.employee', string='Responsable')
    allowed_member_ids = fields.Many2many('hr.employee', string='Responsables', readonly=True)
    task_board_id = fields.Many2one('task.board', string='Grupo', related='subtask_id.task_id', store=True)

    # Campos para almacenar la información del campo dinámico
    dynamic_field_name = fields.Char(string='Nombre Técnico del Campo')
    dynamic_field_label = fields.Char(string='Etiqueta del Campo')
    dynamic_field_type = fields.Selection([
        ('char', 'Texto'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('boolean', 'Booleano'),
        ('selection', 'Selección')],
        string='Tipo de Campo'
    )
    selection_options = fields.Text(string='Opciones de Selección')
    default_value = fields.Text(string='Valor por Defecto')

    def open_dynamic_field_wizard(self):
        """Abre el wizard para crear campos dinámicos"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crear Campo Dinámico',
            'res_model': 'add.field.subtask.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
                'default_task_board_id': self.task_board_id.id,
            }
        }

    def action_create_dynamic_field(self):
        """Crea el campo dinámico en la actividad"""
        self.ensure_one()
        
        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise UserError(_("¡Error! El nombre técnico y tipo de campo son obligatorios"))
        
        # Generar nombre técnico con prefijo
        field_name = self._generate_field_name()
        
        # Verificar si el campo ya existe
        if self._field_exists(field_name):
            raise UserError(_("¡Error! El campo %s ya existe") % field_name)
        
        # Crear el campo en la base de datos
        self._create_field_in_db(field_name)
        
        # Crear registro en ir.model.fields
        self._create_ir_model_field(field_name)
        
        # Actualizar vistas
        self._update_views(field_name)
        
        # Forzar actualización del modelo
        self._reload_model()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def _generate_field_name(self):
        """Genera nombre técnico válido con prefijo x_"""
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '', self.dynamic_field_name.strip().lower().replace(' ', '_'))
        return f'x_{clean_name}' if not clean_name.startswith('x_') else clean_name

    def _field_exists(self, field_name):
        """Verifica si el campo ya existe"""
        return bool(self.env['ir.model.fields'].search([
            ('model', '=', 'subtask.activity'),
            ('name', '=', field_name)
        ]))

    def _create_field_in_db(self, field_name):
        """Crea la columna física en la base de datos"""
        column_type = {
            'char': 'VARCHAR(255)',
            'integer': 'INTEGER',
            'float': 'NUMERIC',
            'boolean': 'BOOLEAN',
            'date': 'DATE',
            'datetime': 'TIMESTAMP',
            'selection': 'VARCHAR(255)'
        }.get(self.dynamic_field_type)
        
        try:
            self.env.cr.execute(f"""
                ALTER TABLE subtask_activity 
                ADD COLUMN {field_name} {column_type}
            """)
            _logger.info("Columna %s creada en BD", field_name)
        except Exception as e:
            _logger.error("Error creando columna: %s", str(e))
            raise UserError(_("Error técnico al crear el campo. Consulte los logs."))

    def _create_ir_model_field(self, field_name):
        """Crea el registro en ir.model.fields"""
        model_id = self.env['ir.model'].search([('model', '=', 'subtask.activity')], limit=1)
        if not model_id:
            raise UserError(_("Modelo subtask.activity no encontrado"))
        
        field_vals = {
            'name': field_name,
            'model_id': model_id.id,
            'field_description': self.dynamic_field_label or self.dynamic_field_name,
            'ttype': self.dynamic_field_type,
            'state': 'manual',
            'store': True,
        }
        
        # Manejar campos de selección
        if self.dynamic_field_type == 'selection' and self.selection_options:
            options = []
            for line in self.selection_options.split('\n'):
                line = line.strip()
                if line and ':' in line:
                    key, val = line.split(':', 1)
                    options.append((key.strip(), val.strip()))
            if options:
                field_vals['selection'] = str(options)
        
        try:
            self.env['ir.model.fields'].create(field_vals)
            _logger.info("Campo %s registrado en ir.model.fields", field_name)
        except Exception as e:
            _logger.error("Error registrando campo: %s", str(e))
            raise UserError(_("Error al registrar el campo. Consulte los logs."))

    def _update_views(self, field_name):
        """Actualiza las vistas para incluir el nuevo campo"""
        try:
            # Vista Tree - Crear una vista heredada
            tree_view = self.env.ref('task_planner.view_subtask_activity_tree', raise_if_not_found=False)
            
            if tree_view:
                arch_tree = f"""
                <xpath expr="//field[@name='person']" position="after">
                    <field name="{field_name}" invisible="context.get('subtask_id') != 1"/>/>
                </xpath>
                """
                
                # Crear vista heredada para tree
                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.tree.{field_name}',
                    'model': 'subtask.activity',
                    'inherit_id': tree_view.id,
                    'arch': arch_tree,
                    'type': 'tree',
                })
            
            # Vista Form - Crear una vista heredada
            form_view = self.env.ref('task_planner.view_subtask_activity_form', raise_if_not_found=False)
            
            if form_view:
                arch_form = f"""
                <xpath expr="//field[@name='person']" position="after">
                    <field name="{field_name}" string="{self.dynamic_field_label or self.dynamic_field_name}"/>

                </xpath>
                """
                
                # Crear vista heredada para form
                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.form.{field_name}',
                    'model': 'subtask.activity',
                    'inherit_id': form_view.id,
                    'arch': arch_form,
                    'type': 'form',
                })
            
            _logger.info("Vistas actualizadas con campo %s", field_name)
            
        except Exception as e:
            _logger.error("Error actualizando vistas: %s", str(e))
            raise UserError(_("Error al actualizar vistas. Consulte los logs."))

    def _reload_model(self):
        """Fuerza la recarga del modelo en el registro"""
        self.env.registry.clear_cache()
        self.env['ir.model'].clear_caches()
        self.env['ir.model.fields'].clear_caches()
        self.env['ir.ui.view'].clear_caches()
        self.env.registry.setup_models(self.env.cr)

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        """Override to add dynamic fields to views"""
        res = super(SubtaskActivity, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        
        # Solo procesar para vistas tree y form
        if view_type in ['tree', 'form']:
            try:
                doc = etree.XML(res['arch'])
                
                # Buscar campos dinámicos
                dynamic_fields = self.env['ir.model.fields'].search([
                    ('model', '=', 'subtask.activity'),
                    ('name', 'like', 'x_%'),
                    ('state', '=', 'manual')
                ])
                
                if dynamic_fields:
                    # Para vista tree, agregar después del campo 'person'
                    if view_type == 'tree':
                        person_fields = doc.xpath("//field[@name='person']")
                        if person_fields:
                            person_field = person_fields[0]
                            for field in dynamic_fields:
                                # Verificar si el campo ya existe en la vista
                                if not doc.xpath(f"//field[@name='{field.name}']"):
                                    field_elem = etree.Element('field', {
                                        'name': field.name,
                                        'string': field.field_description,
                                        'optional': 'show'
                                    })
                                    person_field.addnext(field_elem)
                    
                    # Para vista form, agregar en un grupo específico o después de 'person'
                    elif view_type == 'form':
                        # Buscar grupo de campos dinámicos o crear uno
                        dynamic_group = doc.xpath("//group[@name='dynamic_fields']")
                        if not dynamic_group:
                            # Buscar campo person para insertar después
                            person_fields = doc.xpath("//field[@name='person']")
                            if person_fields:
                                person_field = person_fields[0]
                                parent = person_field.getparent()
                                # Crear grupo para campos dinámicos
                                group_elem = etree.Element('group', {
                                    'name': 'dynamic_fields',
                                    'string': 'Campos Dinámicos'
                                })
                                person_field.addnext(group_elem)
                                dynamic_group = [group_elem]
                        
                        if dynamic_group:
                            group_elem = dynamic_group[0]
                            for field in dynamic_fields:
                                if not doc.xpath(f"//field[@name='{field.name}']"):
                                    field_elem = etree.Element('field', {
                                        'name': field.name,
                                        'string': field.field_description
                                    })
                                    group_elem.append(field_elem)
                
                res['arch'] = etree.tostring(doc, encoding='unicode')
                
            except Exception as e:
                _logger.error("Error procesando vista dinámica: %s", str(e))
        
        return res