SELECT
    c.tag AS country,
    COUNT(*) AS products,
    SUM(p.nutriscore_grade IS NOT NULL) AS graded,
    ROUND(AVG(p.nutriscore_grade IS NOT NULL), 4) AS graded_share,
    ROUND(AVG(p.has_ingredients_text), 4) AS ingredients_text_share
FROM product AS p
JOIN product_country AS pc ON pc.product_id = p.product_id
JOIN country AS c ON c.country_id = pc.country_id
GROUP BY c.tag
HAVING COUNT(*) >= 100
ORDER BY products DESC
LIMIT 25;
