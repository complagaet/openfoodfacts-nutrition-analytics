WITH salt AS (
    SELECT p.product_id, p.food_group_id, pn.value_100g AS salt_100g
    FROM product AS p
    JOIN product_nutrient AS pn ON pn.product_id = p.product_id
    WHERE pn.nutrient_id = (SELECT nutrient_id FROM nutrient WHERE name = 'salt_100g')
),
group_mean AS (
    SELECT food_group_id, AVG(salt_100g) AS mean_salt_100g
    FROM salt
    GROUP BY food_group_id
)
SELECT
    fg.name AS food_group,
    COUNT(*) AS products_with_salt,
    ROUND(gm.mean_salt_100g, 3) AS mean_salt_100g,
    SUM(s.salt_100g > gm.mean_salt_100g) AS above_group_mean,
    ROUND(AVG(s.salt_100g > gm.mean_salt_100g), 4) AS share_above_group_mean
FROM salt AS s
JOIN group_mean AS gm ON gm.food_group_id = s.food_group_id
JOIN food_group AS fg ON fg.food_group_id = s.food_group_id
WHERE s.product_id IN (SELECT product_id FROM product WHERE nutriscore_grade IS NOT NULL)
GROUP BY fg.name, gm.mean_salt_100g
ORDER BY mean_salt_100g DESC;
