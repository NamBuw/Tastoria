import * as ImagePicker from 'expo-image-picker';
import { Image } from 'expo-image';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { api, call, isCode, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { Icon } from '@/components/domain';
import { Button, Checkbox, ErrorBox, Notice, Radio, Row, Screen, T } from '@/components/ui';
import { useIdempotencyKey } from '@/lib/idempotency';
import { imagePart, prepareImage, type PreparedImage } from '@/lib/image';
import { useHasConsent } from '@/lib/queries';
import { radius, space, useTheme } from '@/theme';

/** Quét (UC12): 1–2 photos, resized to 1280 px JPEG, POST /scans with Idempotency-Key, then long-poll. */
export default function Scan() {
  const { c } = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{ mode?: string }>();
  const [mode, setMode] = useState<Schemas['ScanMode']>(params.mode === 'haul' ? 'haul' : 'fridge');
  const [images, setImages] = useState<PreparedImage[]>([]);
  const [contribute, setContribute] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [notOpen, setNotOpen] = useState(false);
  const photoConsent = useHasConsent('photo_contribution');
  const idem = useIdempotencyKey();

  const add = async (camera: boolean) => {
    setErr(null);
    const opts: ImagePicker.ImagePickerOptions = {
      mediaTypes: ['images'],
      quality: 1,
      allowsMultipleSelection: !camera,
      selectionLimit: 2 - images.length,
    };
    if (camera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        setErr(new Error('camera'));
        return;
      }
    }
    const res = camera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (res.canceled) return;
    setBusy(true);
    try {
      const prepared = await Promise.all(res.assets.slice(0, 2 - images.length).map((a) => prepareImage(a.uri)));
      setImages((s) => [...s, ...prepared].slice(0, 2));
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    setBusy(true);
    setErr(null);
    try {
      const key = idem.keyFor({ mode, images: images.map((i) => i.uri), contribute });
      const parts = await Promise.all(images.map((img, i) => imagePart(img, `anh-${i + 1}.jpg`)));
      const accepted = await call(
        api.POST('/scans', {
          params: { header: { 'Idempotency-Key': key } },
          body: { mode, images: [], contribute } as unknown as Schemas['ScanCreate'],
          bodySerializer: () => {
            const fd = new FormData();
            fd.append('mode', mode);
            fd.append('contribute', String(contribute && photoConsent));
            parts.forEach((p, i) => fd.append('images', p as Blob, `anh-${i + 1}.jpg`));
            return fd;
          },
        }),
      );
      idem.reset();
      router.replace({ pathname: '/quet/[id]', params: { id: accepted.id } });
    } catch (e) {
      // POST /scans never answers 404 by contract: a 404 means the scan module is not deployed on this server
      if (isCode(e, 'not_found')) setNotOpen(true);
      else setErr(e);
    } finally {
      setBusy(false);
    }
  };

  if (notOpen) {
    return (
      <Screen testID="screen-scan-closed">
        <Notice tone="warn">
          <T v="title">Quét ảnh chưa mở</T>
          <T>Máy chủ này chưa chạy phần nhận diện ảnh. Bạn vẫn thêm được đồ vào kho bằng tay; mâm cơm ghép từ kho như bình thường.</T>
        </Notice>
        <Button label="Thêm đồ bằng tay trong Kho" onPress={() => router.replace('/kho')} />
        <Button label="Quay lại" kind="ghost" onPress={() => router.back()} />
      </Screen>
    );
  }

  return (
    <Screen
      testID="screen-scan"
      footer={<Button label="Gửi ảnh để nhận diện" testID="scan-send" onPress={send} loading={busy} disabled={!images.length} />}>
      <Row>
        <Radio label="Toàn tủ lạnh" selected={mode === 'fridge'} onPress={() => setMode('fridge')} />
        <Radio label="Đồ vừa mua" selected={mode === 'haul'} onPress={() => setMode('haul')} />
      </Row>
      <T tone="muted">
        {mode === 'fridge'
          ? 'Mở cửa tủ, chụp thẳng từng ngăn, đủ sáng. Tối đa 2 ảnh.'
          : 'Bày đồ vừa mua ra bàn, không chồng lên nhau. Ngày mua được ghi là hôm nay.'}
      </T>
      <Row gap={space.md}>
        {images.map((img, i) => (
          <View key={img.uri} style={{ gap: 4 }}>
            <Image
              source={{ uri: img.uri }}
              style={{ width: 150, height: 150, borderRadius: radius.md, backgroundColor: c.surfaceAlt }}
              contentFit="cover"
              accessibilityLabel={`Ảnh ${i + 1}`}
            />
            <Button kind="ghost" label="Bỏ ảnh" onPress={() => setImages((s) => s.filter((x) => x !== img))} />
          </View>
        ))}
      </Row>
      {images.length < 2 ? (
        <View style={{ gap: space.sm }}>
          <Button label="Chụp ảnh" icon={<Icon name="camera" color={c.onAccent} />} onPress={() => add(true)} disabled={busy} testID="scan-camera" />
          <Button label="Chọn ảnh có sẵn" kind="secondary" onPress={() => add(false)} disabled={busy} testID="scan-library" />
        </View>
      ) : null}
      {photoConsent ? (
        <Checkbox
          checked={contribute}
          onChange={setContribute}
          label="Góp ảnh này để cải thiện mô hình"
          sub={<T v="small" tone="muted">Không tích: ảnh gốc bị xoá sau 30 ngày.</T>}
        />
      ) : (
        <T v="small" tone="muted">
          Ảnh gốc bị xoá sau 30 ngày.
        </T>
      )}
      {err instanceof Error && err.message === 'camera' ? (
        <ErrorBox message="Chưa có quyền dùng máy ảnh. Bật trong cài đặt của máy, hoặc chọn ảnh có sẵn." />
      ) : err ? (
        <ErrorBox message={errorText(err)} />
      ) : null}
    </Screen>
  );
}
