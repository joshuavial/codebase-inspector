export interface DeviceRecord {
  deviceId: string;
  label: string;
  revokedAt: number | null;
}

/** Keeps paired devices in memory, keyed by device ID. */
export class DeviceRegistry {
  private devices = new Map<string, DeviceRecord>();

  /** Adds or replaces a device. */
  put(record: DeviceRecord): void {
    this.devices.set(record.deviceId, record);
  }

  get(deviceId: string): DeviceRecord | null {
    return this.devices.get(deviceId) ?? null;
  }

  revoke(deviceId: string, at: number): boolean {
    const record = this.devices.get(deviceId);
    if (!record) return false;
    record.revokedAt = at;
    return true;
  }
}
