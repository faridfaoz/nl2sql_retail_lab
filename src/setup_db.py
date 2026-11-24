"""Repeatable, deterministic fictional retail warehouse. Amounts in MXN."""
import argparse
import random
from datetime import date, timedelta
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'retail.duckdb'

N_SALES = 20000
N_CUSTOMERS = 150


def create(db_path=DB):
    rng = random.Random(20261030)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    for name in ('sales', 'products', 'stores', 'customers', 'suppliers'):
        con.execute(f'DROP TABLE IF EXISTS {name}')
    con.execute('CREATE TABLE suppliers (supplier_id INTEGER PRIMARY KEY, supplier_name VARCHAR, country VARCHAR, lead_time_days INTEGER)')
    con.execute('CREATE TABLE stores (store_id INTEGER PRIMARY KEY, store_name VARCHAR, city VARCHAR, region VARCHAR, opened_date DATE)')
    con.execute('CREATE TABLE products (product_id INTEGER PRIMARY KEY, product_name VARCHAR, category VARCHAR, unit_cost DECIMAL(12,2), list_price DECIMAL(12,2), supplier_id INTEGER)')
    con.execute('CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, customer_name VARCHAR, city VARCHAR, segment VARCHAR, signup_date DATE)')
    con.execute('''CREATE TABLE sales (sale_id INTEGER PRIMARY KEY, sale_date DATE, store_id INTEGER, product_id INTEGER, customer_id INTEGER,
                   quantity INTEGER, unit_price DECIMAL(12,2), discount_pct DECIMAL(5,2), channel VARCHAR,
                   returned BOOLEAN)''')

    suppliers = [(1, 'Textiles del Norte', 'Mexico', 15), (2, 'CalzadoMX', 'Mexico', 20),
                 (3, 'GlobalWear', 'China', 45), (4, 'TechSource', 'Taiwan', 30),
                 (5, 'HomeFactory', 'Vietnam', 40), (6, 'SportPro', 'USA', 25)]
    stores = [(1, 'Centro', 'Ciudad de Mexico', 'Centro', date(2019, 3, 15)),
              (2, 'Norte', 'Monterrey', 'Norte', date(2020, 6, 1)),
              (3, 'Occidente', 'Guadalajara', 'Occidente', date(2018, 9, 20)),
              (4, 'Sur', 'Puebla', 'Sur', date(2021, 2, 10)),
              (5, 'Coyoacan', 'Ciudad de Mexico', 'Centro', date(2022, 8, 5)),
              (6, 'Bajio', 'Queretaro', 'Bajio', date(2023, 4, 18)),
              (7, 'Golfo', 'Veracruz', 'Golfo', date(2022, 11, 30)),
              (8, 'Maya', 'Merida', 'Sureste', date(2024, 1, 25))]
    products = [(1, 'Camiseta', 'Ropa', 110, 250, 1), (2, 'Jeans', 'Ropa', 320, 690, 1),
                (3, 'Chamarra', 'Ropa', 580, 1290, 3), (4, 'Vestido', 'Ropa', 260, 590, 3),
                (5, 'Tenis', 'Calzado', 550, 1150, 2), (6, 'Botas', 'Calzado', 720, 1590, 2),
                (7, 'Sandalias', 'Calzado', 180, 420, 2), (8, 'Zapatos formales', 'Calzado', 640, 1380, 3),
                (9, 'Mochila', 'Accesorios', 200, 470, 1), (10, 'Cinturon', 'Accesorios', 90, 220, 1),
                (11, 'Gorra', 'Accesorios', 60, 150, 3), (12, 'Bufanda', 'Accesorios', 70, 180, 3),
                (13, 'Audifonos', 'Electronica', 450, 990, 4), (14, 'Cargador', 'Electronica', 95, 260, 4),
                (15, 'Bocina bluetooth', 'Electronica', 380, 820, 4), (16, 'Smartwatch', 'Electronica', 890, 1890, 4),
                (17, 'Botella', 'Hogar', 80, 210, 5), (18, 'Lampara', 'Hogar', 230, 570, 5),
                (19, 'Cobija', 'Hogar', 310, 690, 5), (20, 'Jarron', 'Hogar', 140, 350, 5),
                (21, 'Mancuernas', 'Deportes', 350, 780, 6), (22, 'Bicicleta', 'Deportes', 2800, 5900, 6),
                (23, 'Balon', 'Deportes', 250, 560, 6), (24, 'Tapete de yoga', 'Deportes', 220, 490, 6)]
    first_names = ['Maria', 'Juan', 'Ana', 'Luis', 'Carmen', 'Jose', 'Lucia', 'Diego', 'Sofia', 'Miguel',
                   'Elena', 'Pablo', 'Valeria', 'Andres', 'Renata', 'Emilio', 'Ximena', 'Ricardo', 'Paola', 'Tomas']
    last_names = ['Garcia', 'Martinez', 'Lopez', 'Hernandez', 'Ramirez', 'Torres', 'Flores', 'Rivera',
                  'Gomez', 'Diaz', 'Reyes', 'Cruz', 'Morales', 'Ortiz', 'Gutierrez', 'Chavez',
                  'Mendoza', 'Vargas', 'Castillo', 'Romero']
    cities = ['Ciudad de Mexico', 'Monterrey', 'Guadalajara', 'Puebla', 'Queretaro', 'Veracruz', 'Merida', 'Toluca']
    combos = [f'{f} {l}' for f in first_names for l in last_names]
    customers = []
    for i, name in enumerate(rng.sample(combos, N_CUSTOMERS), start=1):
        segment = rng.choices(['Premium', 'Frecuente', 'Ocasional'], weights=[25, 45, 30])[0]
        signup = date(2024, 1, 1) + timedelta(days=rng.randrange(730))
        customers.append((i, name, rng.choice(cities), segment, signup))
    con.executemany('INSERT INTO suppliers VALUES (?,?,?,?)', suppliers)
    con.executemany('INSERT INTO stores VALUES (?,?,?,?,?)', stores)
    con.executemany('INSERT INTO products VALUES (?,?,?,?,?,?)', products)
    con.executemany('INSERT INTO customers VALUES (?,?,?,?,?)', customers)

    records = []
    first = date(2026, 1, 1)
    store_weights = [20, 14, 14, 12, 10, 10, 10, 10]
    for i in range(1, N_SALES + 1):
        day = first + timedelta(days=rng.randrange(365))  # Jan 1 through Dec 31, 2026
        store = rng.choices(range(1, 9), weights=store_weights)[0]
        product = rng.randrange(1, 25)
        channel = rng.choice(['Tienda', 'Tienda', 'Online'])
        # Online sales always identify the customer; in-store sales do so only for loyalty members.
        customer = rng.randrange(1, N_CUSTOMERS + 1) if channel == 'Online' or rng.random() < 0.5 else None
        qty = rng.randrange(1, 6)
        price = products[product - 1][4]
        discount = rng.choice([0, 0, 0, 0.05, 0.10, 0.15])
        returned = rng.random() < 0.035
        records.append((i, day, store, product, customer, qty, price, discount, channel, returned))
    con.executemany('INSERT INTO sales VALUES (?,?,?,?,?,?,?,?,?,?)', records)
    print(f'Created {db_path} with {len(stores)} stores, {len(products)} products, '
          f'{len(customers)} customers, {len(suppliers)} suppliers, {len(records)} sales rows')
    con.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--db', default=str(DB)); a = p.parse_args(); create(a.db)
