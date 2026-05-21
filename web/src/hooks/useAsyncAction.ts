import { App } from 'antd';
import { useState } from 'react';

export function useAsyncAction() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);

  async function run<T>(action: () => Promise<T>, success?: string): Promise<T | undefined> {
    setLoading(true);
    try {
      const result = await action();
      if (success) message.success(success);
      return result;
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
      return undefined;
    } finally {
      setLoading(false);
    }
  }

  return { loading, run };
}
