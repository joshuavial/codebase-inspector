import assert from "node:assert/strict";
import test from "node:test";
import { DeviceRegistry } from "./registry";

const VALID = { deviceId: "d_1", label: "Phone", revokedAt: null };

test("stores and returns a device", () => {
  const registry = new DeviceRegistry();
  registry.put(VALID);
  assert.deepEqual(registry.get("d_1"), VALID);
});

test("revokes a device", () => {
  const registry = new DeviceRegistry();
  registry.put({ ...VALID });
  assert.equal(registry.revoke("d_1", 5), true);
  assert.equal(registry.get("d_1")?.revokedAt, 5);
});
