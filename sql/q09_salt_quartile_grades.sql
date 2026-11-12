WITH graded_salt AS (
    SELECT
        p.nutriscore_grade AS grade,
        NTILE(4) OVER (ORDER BY pn.value_100g) AS salt_quartile
    FROM product AS p
    JOIN product_nutrient AS pn ON pn.product_id = p.product_id
    JOIN nutrient AS n ON n.nutrient_id = pn.nutrient_id AND n.name = 'salt_100g'
    WHERE p.nutriscore_grade IS NOT NULL
)
SELECT
    salt_quartile,
    grade,
    COUNT(*) AS products,
    ROUND(1.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY salt_quartile), 4) AS share_in_quartile
FROM graded_salt
GROUP BY salt_quartile, grade
ORDER BY salt_quartile, grade;
