// Shortest-column masonry packer — the one packer every bento-style grid in
// the app shares, so tiles always pack identically (never a second copy).
//
// Place each next item in the column with the smallest accumulated height.
// Heights are unitless (height/width ratios) since every column shares a width —
// pixels cancel out. `dimResolver(item)` returns { width, height }.
export const buildColumns = (items, columnCount, dimResolver) => {
  const columns = Array.from({ length: columnCount }, () => ({ height: 0, items: [] }));
  for (const item of items) {
    let shortest = 0;
    for (let i = 1; i < columnCount; i++) {
      if (columns[i].height < columns[shortest].height) shortest = i;
    }
    const { width, height } = dimResolver(item);
    columns[shortest].items.push(item);
    columns[shortest].height += (height || 1) / (width || 1);
  }
  return columns;
};
