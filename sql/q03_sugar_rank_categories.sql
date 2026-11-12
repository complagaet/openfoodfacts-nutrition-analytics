WITH sugars AS (
    SELECT pn.product_id, pn.value_100g AS sugars_100g
    FROM product_nutrient AS pn
    JOIN nutrient AS n ON n.nutrient_id = pn.nutrient_id
    WHERE n.name = 'sugars_100g'
),
category_sugar AS (
    SELECT
        fg.name AS food_group,
        cat.tag AS category,
        COUNT(*) AS products,
        AVG(s.sugars_100g) AS mean_sugars_100g
    FROM sugars AS s
    JOIN product AS p ON p.product_id = s.product_id
    JOIN food_group AS fg ON fg.food_group_id = p.food_group_id
    JOIN product_category AS pcat ON pcat.product_id = p.product_id
    JOIN category AS cat ON cat.category_id = pcat.category_id
    WHERE fg.name <> 'unknown'
    GROUP BY fg.name, cat.tag
    HAVING COUNT(*) >= 30
),
ranked AS (
    SELECT
        *,
        RANK() OVER (PARTITION BY food_group ORDER BY mean_sugars_100g DESC) AS sugar_rank
    FROM category_sugar
)
SELECT food_group, category, products, ROUND(mean_sugars_100g, 2) AS mean_sugars_100g, sugar_rank
FROM ranked
WHERE sugar_rank <= 3
ORDER BY food_group, sugar_rank;
