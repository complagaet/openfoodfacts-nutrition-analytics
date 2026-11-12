CREATE INDEX idx_product_country_country ON product_country (country_id, product_id);
CREATE INDEX idx_product_category_category ON product_category (category_id, product_id);
CREATE INDEX idx_product_nutrient_nutrient ON product_nutrient (nutrient_id, product_id);
CREATE INDEX idx_product_food_group ON product (food_group_id);
CREATE INDEX idx_product_grade ON product (nutriscore_grade);
ANALYZE;
