SELECT
    fg.name AS food_group,
    p.with_non_nutritive_sweeteners AS has_sweetener,
    COUNT(*) AS products,
    ROUND(AVG(pn.value_100g), 2) AS mean_sugars_100g,
    ROUND(AVG(p.nutriscore_grade IN ('a', 'b')), 4) AS share_grade_ab
FROM product AS p
JOIN food_group AS fg ON fg.food_group_id = p.food_group_id
JOIN product_nutrient AS pn ON pn.product_id = p.product_id
JOIN nutrient AS n ON n.nutrient_id = pn.nutrient_id AND n.name = 'sugars_100g'
WHERE p.with_non_nutritive_sweeteners IS NOT NULL
GROUP BY fg.name, p.with_non_nutritive_sweeteners
HAVING COUNT(*) >= 30
ORDER BY fg.name, has_sweetener;
