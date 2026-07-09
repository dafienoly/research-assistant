import StockPool from "../StockPool"
describe("StockPool page", () => {
  it("can be imported", () => {
    expect(StockPool).toBeDefined()
    expect(typeof StockPool).toBe("function")
  })
})