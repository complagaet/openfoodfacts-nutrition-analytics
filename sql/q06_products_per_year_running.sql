WITH yearly AS (
    SELECT created_year, COUNT(*) AS products, SUM(nutriscore_grade IS NOT NULL) AS graded
    FROM product
    WHERE created_year IS NOT NULL
    GROUP BY created_year
)
SELECT
    created_year,
    products,
    graded,
    SUM(products) OVER (ORDER BY created_year) AS cumulative_products,
    products - LAG(products) OVER (ORDER BY created_year) AS change_vs_previous_year
FROM yearly
ORDER BY created_year;
