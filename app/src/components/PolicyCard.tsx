import { useState } from 'react';
import { View } from 'react-native';

import type { Schemas } from '@/api/client';
import { space } from '@/theme';

import { Card, Checkbox, LinkButton, T } from './ui';

/** One consent purpose: unchecked box, what data, why, policy version, full text on demand (BR-CONSENT-01). */
export function PolicyCard({
  policy,
  checked,
  onChange,
}: {
  policy: Schemas['PolicyVersion'];
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const p = policy.purpose;
  return (
    <Card>
      <Checkbox
        testID={`consent-${p.code}`}
        checked={checked}
        onChange={onChange}
        label={`${p.name_vi}${p.is_sensitive ? ' (dữ liệu nhạy cảm)' : ''}`}
        sub={
          <View style={{ gap: 2 }}>
            <T tone="muted">{p.description_vi}</T>
            <T v="small" tone="muted">
              Dữ liệu: {p.data_category}
            </T>
            <T v="small" tone="muted">
              Điều khoản phiên bản {policy.version}
            </T>
          </View>
        }
      />
      <LinkButton label={open ? 'Ẩn điều khoản' : 'Đọc toàn văn điều khoản'} onPress={() => setOpen(!open)} />
      {open ? (
        <View style={{ gap: space.sm }}>
          <T>{policy.text_vi}</T>
        </View>
      ) : null}
    </Card>
  );
}
