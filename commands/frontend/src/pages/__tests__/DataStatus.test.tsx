import DataStatus from "../DataStatus"
describe("DataStatus page", () => {
  it("can be imported", () => {
    expect(DataStatus).toBeDefined()
    expect(typeof DataStatus).toBe("function")
  })
})