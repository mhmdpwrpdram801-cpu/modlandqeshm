const now=Date.now(), iso=t=>new Date(t).toISOString();
window.__UPLOADS=[]; window.__DELETES=[]; window.__PRIMES=[]; window.__WRITES=[]; window.__OPEN=[];
window.open=(u)=>{ window.__OPEN.push(String(u)); return null; };
const P=[
 {id:'p1',name:"شلوار جین آبی «جنسِ ویژه» <b>۲۰۲۶</b> & کد A-100",price:850000,size_info:'قد ۱۰۰',created_at:iso(now-9e8),
  video_jin_url:null,video_jin_fid:'BAAC_jin_1',video_carton_url:null,video_carton_fid:null,
  photos:[{url:'/icon-192.png',fid:'AgAC1'}]},
 {id:'p2',name:'مانتو مجلسی',price:1250000,size_info:'',created_at:iso(now-3*864e5),
  video_jin_url:null,video_jin_fid:null,video_carton_url:null,video_carton_fid:null,photos:[]},
 {id:'p3',name:'شومیز "طرح‌دار" <ویژه>',price:430000,size_info:'',created_at:iso(now-7e8),
  video_jin_url:null,video_jin_fid:null,video_carton_url:null,video_carton_fid:null,photos:[]}];
const C=[{id:'c3',name:'مشتریِ تازه',phone:'09000000000',city:'قشم',address:'',notes:'',created_at:iso(now-1e8)},
 {id:'c4',name:'فقط باطل',phone:'09111111111',city:'قشم',address:'',notes:'',created_at:iso(now-1e8)},
 {id:'c1',name:'حاج رضا',phone:'09171112233',city:'درگهان',address:'خ اصلی',notes:'',created_at:iso(now-9e8)},
 {id:'c2',name:"مغازه‌ی 'گل'",phone:'09359998877',city:'قشم',address:'',notes:'',created_at:iso(now-5e8)}];
const INV=[
 {id:'i3',invoice_number:1009,buyer_name:'فقط باطل',customer_id:'c4',date:'۱۴۰۵/۰۵/۰۱',items_total:100000,
  discount:0,total_amount:100000,paid_amount:0,status:'cancelled',note:'',created_at:iso(now-3*864e5)},
 {id:'i1',invoice_number:1001,buyer_name:'حاج رضا',buyer_phone:'09171112233',buyer_city:'درگهان',customer_id:'c1',
  date:'۱۴۰۵/۰۵/۰۱',items_total:2550000,discount:50000,total_amount:2500000,paid_amount:1000000,status:'partial',note:'',created_at:iso(now-2*864e5)},
 {id:'i2',invoice_number:1002,buyer_name:"مغازه‌ی 'گل'",customer_id:'c2',date:'۱۴۰۵/۰۵/۰۲',items_total:430000,
  discount:0,total_amount:430000,paid_amount:430000,status:'paid',note:'',created_at:iso(now-864e5)}];
const DATA_BEV=(()=>{ const E=[]; let n=0;
   const e=(chat,event,pid,mins,meta)=>E.push({id:++n,chat_id:chat,event,product_id:pid||null,meta:meta||null,created_at:iso(now-mins*6e4)});
   e(1,'start',null,600);
   e(2,'start',null,590); e(2,'browse',null,589);
   e(3,'start',null,580); e(3,'browse',null,579); e(3,'view','p1',578);
   e(4,'start',null,570); e(4,'browse',null,569); e(4,'view','p1',568); e(4,'media','p1',567);
   e(5,'start',null,560); e(5,'browse',null,559); e(5,'view','p2',558); e(5,'cart_add','p2',557,{qty:1,unit_price:1250000});
   e(6,'start',null,550); e(6,'browse',null,549); e(6,'view','p1',548); e(6,'cart_add','p1',547,{qty:2,unit_price:850000}); e(6,'checkout',null,546,{items:1});
   e(7,'start',null,540); e(7,'browse',null,539); e(7,'view','p1',538); e(7,'cart_add','p1',537,{qty:1,unit_price:850000}); e(7,'checkout',null,536,{items:1}); e(7,'order',null,535,{total:850000,items:1});
   e(8,'start',null,530); e(8,'browse',null,529); e(8,'view','p3',528); e(8,'cart_add','p3',527,{qty:1,unit_price:430000}); e(8,'checkout',null,526,{items:1}); e(8,'order',null,525,{total:430000,items:1}); e(8,'receipt',null,524,{total:430000});
   e(9,'start',null,520); e(9,'browse',null,519); e(9,'view','p1',518); e(9,'cart_add','p1',517,{qty:2,unit_price:850000}); e(9,'checkout',null,516,{items:1}); e(9,'order',null,515,{total:1700000,items:1}); e(9,'receipt',null,514,{total:1700000}); e(9,'paid',null,513,{total:1700000}); e(9,'order',null,120,{total:850000,items:1});
   e(10,'start',null,500); e(10,'ask',null,499);
   return E; })();
const DATA={products:P,customers:C,invoices:INV,
 invoice_items:[{id:'ii1',invoice_id:'i1',product_id:'p1',product_name:"شلوار جین آبی «جنسِ ویژه» <b>۲۰۲۶</b> & کد A-100",quantity:3,unit_price:850000,line_total:2550000,created_at:iso(now-2*864e5)},
                {id:'ii2',invoice_id:'i2',product_id:'p3',product_name:'شومیز',quantity:1,unit_price:430000,line_total:430000,created_at:iso(now-864e5)}],
 payments:[{id:'pay1',customer_id:'c1',amount:1000000,date:'۱۴۰۵/۰۵/۰۱',method:'نقدی',invoice_id:null,note:'',created_at:iso(now-2*864e5)},
           {id:'pay2',customer_id:'c1',amount:400000,date:'۱۴۰۵/۰۵/۰۳',method:'نقدی',invoice_id:'i1',note:'',created_at:iso(now-864e5)}],
 customer_balances:[{id:'c1',name:'حاج رضا',phone:'09171112233',city:'درگهان',balance:1100000},
                    {id:'c2',name:"مغازه‌ی 'گل'",phone:'09359998877',city:'قشم',balance:0}],
 expenses:[{id:'e1',note:'کرایه',amount:300000,date:'۱۴۰۵/۰۵/۰۱',category:'حمل',created_at:iso(now-864e5)}],
 salaries:[{id:'s1',employee_name:'علی',amount:5000000,date:'۱۴۰۵/۰۵/۰۱',month:'۱۴۰۵/۰۵',note:'',created_at:iso(now-864e5)}],
 shipments:[{id:'sh1',customer_name:'حاج رضا',city:'درگهان',qty:3,customer_id:'c1',created_at:iso(now-864e5)},
            {id:'sh2',customer_name:'حاج رضا',city:'بندرعباس',qty:12,customer_id:'c1',created_at:iso(now-3*864e5)},
            /* عمداً وصل‌نشده: نامی که هیچ مشتری‌ای ندارد. صفحه‌ی مشتری نباید
               این را به کسی نسبت بدهد و ارسالی‌ها هم نباید پنهانش کنند. */
            {id:'sh3',customer_name:'یه نفرِ ناشناس',city:'شیراز',qty:6,customer_id:null,created_at:iso(now-5*864e5)}],
 // دو جورِ مرجوعی، دقیقاً مثلِ دیتابیسِ واقعی:
 // r1 مستقل است (create_return) — فاکتوری ندارد، پس باید از فروش کم شود.
 // r2 روی فاکتورِ i2 است (return_invoice_items) — آن تابع خودش جمعِ فاکتور و اقلامش را کم کرده،
 //    یعنی i2 و ii2 که اینجا می‌بینی «بعد از مرجوعی»اند و نباید دوباره کم شوند.
 returns:[{id:'r1',customer_id:'c1',buyer_name:'حاج رضا',date:'۱۴۰۵/۰۵/۰۲',invoice_id:null,
   items:[{product_id:'p1',name:"شلوار جین آبی «جنسِ ویژه» <b>۲۰۲۶</b> & کد A-100",quantity:1,unit_price:850000}],total_value:850000,settlement:'credit',note:'',created_at:iso(now-864e5)},
  {id:'r2',customer_id:'c2',buyer_name:"مغازه‌ی 'گل'",date:'۱۴۰۵/۰۵/۰۲',invoice_id:'i2',
   items:[{product_id:'p3',name:'شومیز',quantity:1,unit_price:430000}],total_value:430000,settlement:'invoice',note:'مرجوعی از فاکتور',created_at:iso(now-864e5)}],
 quotes:[{id:'q1',buyer_name:'حاج رضا',customer_id:'c1',items:[{product_id:'p1',quantity:1,unit_price:850000}],items_total:850000,discount:0,note:'',created_at:iso(now-864e5)}],
 telegram_orders:[{id:'t1',status:'new',customer_name:'زهرا',customer_phone:'09120001122',customer_city:'قشم',customer_address:'خیابان',
   items:[{product_id:'p1',name:"شلوار جین آبی «جنسِ ویژه» <b>۲۰۲۶</b> & کد A-100",quantity:2,unit_price:850000}],total:1700000,note:null,created_at:iso(now-36e5),
   tg_user_id:5,tg_username:'z',paid_confirmed_at:null,card_sent_at:null,receipt_sent_at:null,invoice_id:null}],
 /* ── رفتارِ مشتری در ربات: ده نفر با عمقِ **دستی‌حساب‌شده** ────────────────
     v1 فقط اومد · v2 لیست دید · v3,v4 کالا باز کردن · v5 سبد پر کرد
     v6 رفت سرِ تسویه · v7 سفارش داد · v8 فیش فرستاد · v9 پرداختش تأیید شد
     v10 فقط سؤال پرسید (عمقش مثلِ «لیست دید» است، نه بیشتر)
     پس: ۱۰ بازدیدکننده · ۳ خریدار · نرخِ تبدیل ۳۰٪ · ۱ پرداختِ تأییدشده.
     v9 دو سفارش دارد تا «مشتریِ برگشتی» هم عددِ واقعی داشته باشد. */
 bot_events_public:DATA_BEV,
 /* جدولِ **خام**: همان ده نفرِ بالا، به‌علاوه‌ی یک مدیر (خودِ مالک) که نما
    بیرونش می‌گذارد. پس بازدیدکننده باید ۱۰ باشد و با کلیدِ «ترافیکِ خودم» ۱۱. */
 bot_events:(()=>{ const E=DATA_BEV.slice(); let n=1000;
   const e=(event,pid,mins)=>E.push({id:++n,chat_id:999,event,product_id:pid||null,meta:null,created_at:iso(now-mins*6e4)});
   e('start',null,300); e('browse',null,299); e('view','p1',298);
   return E; })(),
 /* خطاهای گوشی: دو مشکلِ متمایز، یکی سه بار تکرار شده و یکی یک بار.
    پس «۲ مشکلِ متمایز · ۴ بار» — عددِ دستی‌حساب‌شده. */
 client_errors_recent:[
   {id:1,created_at:iso(now-2*36e5),kind:'error',screen:'invoices',app_version:'mlq-70',message:"Cannot read properties of null (reading 'value')"},
   {id:2,created_at:iso(now-3*36e5),kind:'error',screen:'invoices',app_version:'mlq-70',message:"Cannot read properties of null (reading 'value')"},
   {id:3,created_at:iso(now-9*36e5),kind:'error',screen:'invoices',app_version:'mlq-70',message:"Cannot read properties of null (reading 'value')"},
   {id:4,created_at:iso(now-30*36e5),kind:'unhandledrejection',screen:'products',app_version:'mlq-69',message:'<b>خطا</b> & شبکه قطع شد'}],
 /* دو سبدِ نیمه‌کاره — جمعِ دستی: ۱٬۷۰۰٬۰۰۰ + ۸۵۰٬۰۰۰ = ۲٬۵۵۰٬۰۰۰ */
 bot_carts_open:[
   {chat_id:5,customer_name:'زهرا',customer_phone:'09120001122',customer_city:'قشم',cart_items:2,cart_total:1700000,updated_at:iso(now-2*36e5)},
   {chat_id:6,customer_name:"سبدِ <b>بی‌نام</b> & 'خط'",customer_phone:'',customer_city:'',cart_items:1,cart_total:850000,updated_at:iso(now-5*36e5)}],
 discount_codes:[{id:'d1',code:'EID',percent:10,active:true,note:'',created_at:iso(now-864e5)}],
 settings:[{id:1,shop_name:'مدلند قشم',subtitle:'پخش پوشاک',phone:'09171234567',phone2:'',address:'درگهان',
   instagram:'modland',telegram:'modlandqeshm',return_policy:'تا ۷ روز',updated_at:iso(now)}]};
/* `sales_month` قبلاً عددِ ثابتِ ۲٬۹۳۰٬۰۰۰ بود — یعنی استاب «فروشِ این ماه» را
   **بی‌توجه به ماه** می‌داد، حالتی که در دیتابیسِ واقعی ممکن نیست (TEST-05).
   تا وقتی ماهِ جلالیِ امروز همان ماهِ ردیف‌های شبیه‌ساز بود کسی نمی‌فهمید؛ شبِ اولِ
   ماهِ بعد، داشبورد عددِ ماهِ قبل را نشان می‌داد و گزارش درست ۰ — و بررسیِ «داشبورد و
   گزارش یکی‌اند» قرمز می‌شد بی‌آنکه چیزی در پنل خراب باشد.
   حالا getter است و از خودِ ردیف‌ها برای ماهِ جاری حساب می‌شود. getter لازم است چون
   `iranJalaliKey` مالِ خودِ صفحه است و موقعِ بار شدنِ این فایل هنوز وجود ندارد؛ اینجا
   فقط سرِ صدا زدنِ RPC خوانده می‌شود که آن‌وقت صفحه بالا آمده. */
const RPC={
 get dashboard_stats(){
  const K=window.iranJalaliKey;
  const ym=K?K(new Date()).slice(0,7):null;
  const inMonth=r=>!ym||(K(new Date(r.created_at)).slice(0,7)===ym);
  const live=INV.filter(v=>v.status!=='cancelled');
  return {sales_today:430000,
   sales_month:live.filter(inMonth).reduce((s,v)=>s+Number(v.total_amount||0),0),
   profit_today:0,profit_month:0,count_today:1,
   receivables:1100000,exp_month:300000,debtors:[{cid:'c1',name:'حاج رضا',phone:'09171112233',amount:1100000}],
   inactive:[{cid:'c2',name:"مغازه‌ی 'گل'",phone:'09359998877',last:iso(now-40*864e5)}],
   top:[{name:"شلوار جین آبی «جنسِ ویژه» <b>۲۰۲۶</b> & کد A-100",qty:3}],chart:[{d:'2026-07-28',value:430000},{d:'2026-07-29',value:2500000}]};
 },
 create_invoice:{id:'i9',invoice_number:1003,customer_created:false,replayed:false,items_total:2550000,discount:50000,total_amount:2500000,paid_amount:0,status:'credit'},
 cancel_invoice:{ok:true},restore_invoice:{status:'credit'},
 return_invoice_items:{id:'r9',refund:850000,items_total:1700000,total_amount:1650000,status:'partial'},
 convert_telegram_order:{id:'i9',invoice_number:1003,customer_created:true,replayed:false}};
const _f=window.fetch;
window.__FAIL=null;
window.fetch=async(url,opts={})=>{
  url=String(url); const m=(opts.method||'GET').toUpperCase();
  const J=(o,s)=>new Response(JSON.stringify(o),{status:s||200,headers:{'Content-Type':'application/json'}});
  if(window.__FAIL && url.includes(window.__FAIL) && m!=='GET') return J({message:'خطای ساختگی'},500);
  if(url.includes('/auth/v1/token'))return J({access_token:'t',refresh_token:'r',expires_in:3600,user:{id:'u1'}});
  if(url.includes('?prime='))  { window.__PRIMES.push(url); return J({ok:true,jin:'ok',carton:'skip',jin_fid:'BAACnew',carton_fid:null}); }
  if(url.includes('/storage/v1/object/')){ if(m==='DELETE'){window.__DELETES.push(url); return J({});}
    window.__UPLOADS.push({url,size:(opts.body&&opts.body.size)||0}); return J({Key:'ok'}); }
  if(url.includes('/rest/v1/rpc/')){ const fn=url.split('/rpc/')[1].split('?')[0];
    window.__WRITES.push({rpc:fn,body:opts.body?JSON.parse(opts.body):null});
    return J(RPC[fn]!==undefined?RPC[fn]:{}); }
  const table=(url.split('/rest/v1/')[1]||'').split('?')[0];
  if(m!=='GET'){ window.__WRITES.push({table,method:m,body:opts.body?JSON.parse(opts.body):null}); return J([{id:'new1'}]); }
  if(/offset=([1-9]\d*)/.test(url))return J([]);
  let rows=DATA[table]||[];
  /* فیلترها را مثلِ PostgREST اعمال کن — نه با تطبیقِ دستیِ چندتا حالتِ خاص.
     قبلاً is.null اجرا نمی‌شد و فیلترِ جدولِ تودرتو (invoices.customer_id) اشتباهی
     روی خودِ ردیف اعمال می‌شد؛ یعنی تست روی حالتی اجرا می‌شد که در واقعیت ممکن نیست. */
  const EMBED={invoice_items:{invoices:r=>DATA.invoices.find(v=>v.id===r.invoice_id)||{}}};
  const cmp=(a,b)=>{ const na=Number(a),nb=Number(b);
    if(!isNaN(na)&&!isNaN(nb)&&a!==''&&b!=='')return na<nb?-1:na>nb?1:0;
    return String(a)<String(b)?-1:String(a)>String(b)?1:0; };
  (url.split('?')[1]||'').split('&').forEach(part=>{
    const i=part.indexOf('='); if(i<0)return;
    const key=decodeURIComponent(part.slice(0,i));
    if(/^(select|order|limit|offset|or|and|columns)$/.test(key))return;
    const mo=part.slice(i+1).match(/^(eq|neq|gt|gte|lt|lte|is|like|ilike)\.([\s\S]*)$/); if(!mo)return;
    const op=mo[1], val=decodeURIComponent(mo[2]);
    let src=null, col=key;
    if(key.indexOf('.')>0){ const p=key.split('.'); src=p[0]; col=p.slice(1).join('.'); }
    const get=(r)=>{ if(!src)return r[col];
      const f=(EMBED[table]||{})[src]; return f?f(r)[col]:undefined; };
    rows=rows.filter(r=>{ const v=get(r);
      switch(op){
        case 'eq':  return String(v)===val;
        case 'neq': return String(v)!==val;
        case 'is':  return val==='null'?(v==null||v===''):(v!=null&&v!=='');
        case 'gt':  return cmp(v,val)>0;
        case 'gte': return cmp(v,val)>=0;
        case 'lt':  return cmp(v,val)<0;
        case 'lte': return cmp(v,val)<=0;
        case 'like': case 'ilike':{
          const rx=new RegExp('^'+val.replace(/[.*+?^${}()|[\]\\]/g,c=>c==='*'?'*':'\\'+c).replace(/\*/g,'[\\s\\S]*')+'$', op==='ilike'?'i':'');
          return rx.test(String(v==null?'':v)); }
      }
      return true; });
  });
  if(/order=created_at\.desc/.test(url))rows=rows.slice().sort((a,b)=>new Date(b.created_at)-new Date(a.created_at));
  const lm=url.match(/limit=(\d+)/); if(lm)rows=rows.slice(0,+lm[1]);
  return J(rows);
};
