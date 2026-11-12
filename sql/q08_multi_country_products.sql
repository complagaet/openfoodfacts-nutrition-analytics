WITH reach AS (
    SELECT product_id, COUNT(*) AS countries
    FROM product_country
    GROUP BY product_id
)
SELECT
    fg.name AS food_group,
    COUNT(*) AS products,
    SUM(r.countries >= 3) AS sold_in_3plus_countries,
    ROUND(AVG(r.countries), 3) AS mean_countries,
    MAX(r.countries) AS max_countries
FROM reach AS r
JOIN product AS p ON p.product_id = r.product_id
JOIN food_group AS fg ON fg.food_group_id = p.food_group_id
GROUP BY fg.name
HAVING SUM(r.countries >= 3) > 0
ORDER BY sold_in_3plus_countries DESC;
