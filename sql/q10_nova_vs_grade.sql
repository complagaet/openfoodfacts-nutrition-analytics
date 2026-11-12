SELECT
    p.nova_group,
    p.nutriscore_grade AS grade,
    COUNT(*) AS products,
    ROUND(1.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY p.nova_group), 4) AS share_in_nova_group,
    DENSE_RANK() OVER (PARTITION BY p.nova_group ORDER BY COUNT(*) DESC) AS rank_in_nova_group
FROM product AS p
WHERE p.nova_group IS NOT NULL AND p.nutriscore_grade IS NOT NULL
GROUP BY p.nova_group, p.nutriscore_grade
ORDER BY p.nova_group, grade;
