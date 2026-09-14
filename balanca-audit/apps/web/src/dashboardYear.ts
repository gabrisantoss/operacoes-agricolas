export function dashboardPathForYear(path: string, selectedYear: number | null) {
  if (!Number.isInteger(selectedYear) || (selectedYear ?? 0) <= 0) {
    return path;
  }

  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}year=${selectedYear}`;
}
