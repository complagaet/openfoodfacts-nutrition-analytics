PRAGMA foreign_keys = ON;

CREATE TABLE food_group (
    food_group_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE product (
    product_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    product_name TEXT,
    brand TEXT,
    food_group_id INTEGER NOT NULL REFERENCES food_group (food_group_id),
    nutriscore_status TEXT NOT NULL,
    nutriscore_grade TEXT CHECK (nutriscore_grade IN ('a', 'b', 'c', 'd', 'e')),
    nutriscore_score INTEGER,
    nova_group INTEGER CHECK (nova_group BETWEEN 1 AND 4),
    created_year INTEGER,
    has_ingredients_text INTEGER NOT NULL CHECK (has_ingredients_text IN (0, 1)),
    with_non_nutritive_sweeteners INTEGER CHECK (with_non_nutritive_sweeteners IN (0, 1)),
    additives_n INTEGER
);

CREATE TABLE country (
    country_id INTEGER PRIMARY KEY,
    tag TEXT NOT NULL UNIQUE
);

CREATE TABLE product_country (
    product_id INTEGER NOT NULL REFERENCES product (product_id),
    country_id INTEGER NOT NULL REFERENCES country (country_id),
    PRIMARY KEY (product_id, country_id)
) WITHOUT ROWID;

CREATE TABLE category (
    category_id INTEGER PRIMARY KEY,
    tag TEXT NOT NULL UNIQUE
);

CREATE TABLE product_category (
    product_id INTEGER NOT NULL REFERENCES product (product_id),
    category_id INTEGER NOT NULL REFERENCES category (category_id),
    PRIMARY KEY (product_id, category_id)
) WITHOUT ROWID;

CREATE TABLE nutrient (
    nutrient_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    unit TEXT NOT NULL
);

CREATE TABLE product_nutrient (
    product_id INTEGER NOT NULL REFERENCES product (product_id),
    nutrient_id INTEGER NOT NULL REFERENCES nutrient (nutrient_id),
    value_100g REAL NOT NULL CHECK (value_100g >= 0),
    PRIMARY KEY (product_id, nutrient_id)
) WITHOUT ROWID;
