"""Internal yearly-axis preparation; no business series or public API is defined here."""


def annual_axis(year_counts, start_year=None, end_year=None):
    """Fill known-year gaps in an explicit snapshot, keeping unknown years separate.

    Input is the existing distinct-paper aggregation, not raw join rows. A zero
    means no matching *known-year* papers in this snapshot, not global coverage.
    """
    counts, missing = {}, 0
    for row in year_counts:
        count = row['paper_count']
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError('paper_count must be a nonnegative integer')
        year = row['year']
        if year is None:
            missing += count
        elif not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= 2100 or year in counts:
            raise ValueError('unique years in 1900..2100 required')
        else:
            counts[year] = count
    for value in (start_year, end_year):
        if value is not None and (not isinstance(value,int) or isinstance(value,bool) or not 1900<=value<=2100):
            raise ValueError('invalid year bound')
    start = start_year if start_year is not None else min(counts, default=end_year)
    end = end_year if end_year is not None else max(counts, default=start_year)
    if start is not None and end is not None and start > end:
        raise ValueError('year range reversed')
    return dict(points=[dict(year=y,paper_count=counts.get(y,0),observed=y in counts)
                        for y in range(start,end+1)] if start is not None and end is not None else [],
                missing_year_papers=missing, complete_year_metadata=missing==0,
                start_year=start, end_year=end, unit='distinct_papers',
                basis='known publication year in one published snapshot; no batch events or historical accumulation')
