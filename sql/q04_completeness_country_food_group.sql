WITH nutrient_counts AS (
    SELECT p.product_id, p.food_group_id, COUNT(n.nutrient_id) AS core_nutrients
    FROM product AS p
    LEFT JOIN product_nutrient AS pn ON pn.product_id = p.product_id
    LEFT JOIN nutrient AS n ON n.nutrient_id = pn.nutrient_id AND n.name <> 'energy_kj_100g'
    GROUP BY p.product_id, p.food_group_id
),
single_country AS (
    SELECT product_id, MIN(country_id) AS country_id
    FROM product_country
    GROUP BY product_id
    HAVING COUNT(*) = 1
)
SELECT
    c.tag AS country,
    fg.name AS food_group,
    COUNT(*) AS products,
    ROUND(AVG(nc.core_nutrients >= 8), 4) AS complete_share
FROM nutrient_counts AS nc
JOIN single_country AS sc ON sc.product_id = nc.product_id
JOIN country AS c ON c.country_id = sc.country_id
JOIN food_group AS fg ON fg.food_group_id = nc.food_group_id
WHERE fg.name <> 'unknown'
GROUP BY c.tag, fg.name
HAVING COUNT(*) >= 100
ORDER BY fg.name, complete_share DESC;
