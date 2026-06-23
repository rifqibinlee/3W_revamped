export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : page * pageSize + 1
  const to = Math.min(total, (page + 1) * pageSize)

  return (
    <div className="mt-3 flex items-center justify-between text-xs text-white/55">
      <span>
        {total === 0 ? 'No rows' : `${from}-${to} of ${total}`}
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 0}
          className="rounded-lg border border-white/15 px-2.5 py-1 disabled:opacity-30"
        >
          Prev
        </button>
        <span>
          Page {page + 1} of {pageCount}
        </span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page + 1 >= pageCount}
          className="rounded-lg border border-white/15 px-2.5 py-1 disabled:opacity-30"
        >
          Next
        </button>
      </div>
    </div>
  )
}
