import Dashboard from "../Dashboard"
describe("Dashboard page", () => {
  it("can be imported", () => {
    expect(Dashboard).toBeDefined()
    expect(typeof Dashboard).toBe("function")
  })
})