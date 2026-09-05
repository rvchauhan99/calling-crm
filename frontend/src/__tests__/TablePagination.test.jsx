import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import {
  TablePagination,
  paginationRange,
  clampPageSize,
} from "@/components/TablePagination"

describe("paginationRange", () => {
  it("returns zeros for empty total", () => {
    expect(paginationRange(1, 25, 0)).toEqual({ from: 0, to: 0 })
  })

  it("computes full page range", () => {
    expect(paginationRange(2, 25, 100)).toEqual({ from: 26, to: 50 })
  })

  it("clamps last partial page", () => {
    expect(paginationRange(2, 25, 40)).toEqual({ from: 26, to: 40 })
  })
})

describe("clampPageSize", () => {
  it("accepts allowed sizes and falls back otherwise", () => {
    expect(clampPageSize(50)).toBe(50)
    expect(clampPageSize(30)).toBe(25)
    expect(clampPageSize("bad")).toBe(25)
  })
})

describe("TablePagination", () => {
  it("shows range and page label for multi-page totals", () => {
    render(
      <TablePagination
        page={2}
        pageSize={25}
        total={100}
        onPageChange={jest.fn()}
        onPageSizeChange={jest.fn()}
      />,
    )
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("26–50 of 100")
    expect(screen.getByTestId("pagination-page-label")).toHaveTextContent("Page 2 of 4")
  })

  it("calls onPageSizeChange when rows-per-page changes", async () => {
    const onPageSizeChange = jest.fn()
    render(
      <TablePagination
        page={1}
        pageSize={25}
        total={100}
        onPageChange={jest.fn()}
        onPageSizeChange={onPageSizeChange}
      />,
    )
    await userEvent.selectOptions(screen.getByTestId("page-size-select"), "50")
    expect(onPageSizeChange).toHaveBeenCalledWith(50)
  })

  it("disables Prev on first page and Next on last page", () => {
    const { rerender } = render(
      <TablePagination
        page={1}
        pageSize={25}
        total={40}
        onPageChange={jest.fn()}
        onPageSizeChange={jest.fn()}
      />,
    )
    expect(screen.getByTestId("prev-page")).toBeDisabled()
    expect(screen.getByTestId("next-page")).not.toBeDisabled()

    rerender(
      <TablePagination
        page={2}
        pageSize={25}
        total={40}
        onPageChange={jest.fn()}
        onPageSizeChange={jest.fn()}
      />,
    )
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("26–40 of 40")
    expect(screen.getByTestId("prev-page")).not.toBeDisabled()
    expect(screen.getByTestId("next-page")).toBeDisabled()
  })

  it("renders nothing when total is zero", () => {
    const { container } = render(
      <TablePagination
        page={1}
        pageSize={25}
        total={0}
        onPageChange={jest.fn()}
        onPageSizeChange={jest.fn()}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("calls onPageChange from Prev and Next", async () => {
    const onPageChange = jest.fn()
    render(
      <TablePagination
        page={2}
        pageSize={25}
        total={100}
        onPageChange={onPageChange}
        onPageSizeChange={jest.fn()}
      />,
    )
    await userEvent.click(screen.getByTestId("prev-page"))
    expect(onPageChange).toHaveBeenCalledWith(1)
    await userEvent.click(screen.getByTestId("next-page"))
    expect(onPageChange).toHaveBeenCalledWith(3)
  })
})
