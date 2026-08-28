const r = await fetch(u, {
  body: s,
  // @ts-ignore
  duplex: 'half',
});
