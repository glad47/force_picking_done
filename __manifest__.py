{
    'name': 'Force Picking Done',
    'version': '16.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Override stock picking validation to force done',
    'description': """
        Overrides the default validate behavior of stock pickings
        to force them to done state without validation.
        
        WARNING: This bypasses all inventory validation!
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['stock', 'purchase_stock'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
