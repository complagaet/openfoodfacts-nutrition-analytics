WITH top_countries AS (
    SELECT pc.country_id
    FROM product_country AS pc
    JOIN product AS p ON p.product_id = pc.product_id
    WHERE p.nutriscore_grade IS NOT NULL
    GROUP BY pc.country_id
    ORDER BY COUNT(*) DESC
    LIMIT 10
),
grade_counts AS (
    SELECT c.tag AS country, p.nutriscore_grade AS grade, COUNT(*) AS products
    FROM product AS p
    JOIN product_country AS pc ON pc.product_id = p.product_id
    JOIN top_countries AS t ON t.country_id = pc.country_id
    JOIN country AS c ON c.country_id = pc.country_id
    WHERE p.nutriscore_grade IS NOT NULL
    GROUP BY c.tag, p.nutriscore_grade
)
SELECT
    country,
    grade,
    products,
    ROUND(1.0 * products / SUM(products) OVER (PARTITION BY country), 4) AS share_in_country
FROM grade_counts
ORDER BY country, grade;
