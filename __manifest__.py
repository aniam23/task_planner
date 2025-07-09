# -*- coding: utf-8 -*-
{
    'name': "Task and Activity Planner",

    'summary': """
        Can see activity or task designed to user specifically""",

    'description': """
        Designed to add or modify task designed to user
    """,

    'author': "Obed David Cano Mendez",
    'website': "http://www.horizontrailers.com",
    'sequence': 1,

    'version': '1.0',
    
    'depends': ['base', 'web', 'mail', 'hr'],

    'data': [
    'security/ir.model.access.csv',  
    'security/boards_security.xml',  
    'views/boards_view.xml',         
    'views/task_view.xml',
    'views/sub_task_view.xml',
    'views/menu.xml',
    ],
    
    'installable': True,
    'application': True,
    'license': 'GPL-3',
}