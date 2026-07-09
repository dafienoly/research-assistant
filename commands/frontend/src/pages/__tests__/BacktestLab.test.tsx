import BacktestLab from "../BacktestLab"
describe("BacktestLab page", () => {
  it("can be imported", () => {
    expect(BacktestLab).toBeDefined()
    expect(typeof BacktestLab).toBe("function")
  })
})