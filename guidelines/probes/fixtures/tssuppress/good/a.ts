const r = await fetch(u, {
  body: s,
  // @ts-expect-error — duplex در تایپِ RequestInit نیست ولی لازم است
  duplex: 'half',
});
