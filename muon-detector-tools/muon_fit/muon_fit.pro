pro muon_fit, gplot=gplot, hplot=hplot, ps=ps, crplot=crplot, verbose=verbose, ptc=ptc
;+
;  muon_fit - fit muons in the dark image sets
;-
; initial params
bs=0.025
cd,current=cwd
sta=strsplit(cwd,'/',/extract)
cwd = sta[n_elements(sta)-1]
;
; keywords
if keyword_set(ptc) then begin
	mw0 = 0.62
	mw1 = 0.73
	xlim = [5,20]
endif else begin
	mw0 = 0.52
	mw1 = 0.60
	xlim = [5,15]
endelse
; read data
;
; get image list
imlist = file_search('im??.fits', count=nf)
if nf le 0 then imlist = file_search('im???.fits', count=nf)
allbig = fltarr(5000)
allsmall = fltarr(5000)
p = 0L
;
; loop over images
for k=0,nf-1 do begin
    imf = imlist[k]
    im = mrdfits(imf, 0, imhdr, /silent)
    seg = mrdfits(strmid(imf, 0, strpos(imf,'.'))+'_seg.fits', 0, sghdr,/silent)
    readcol,strmid(imf, 0, strpos(imf,'.'))+'_cr.cat', $
	sids, xs, ys, xrms, yrms, thetas, format='i,f,f,f,f,f', $
	comment='#',/silent
    ;
    ; convert thetas to radians
    thetas = thetas * !pi / 180.
    ;
    nseg = n_elements(sids)
    big = fltarr(nseg) - 1.
    small = fltarr(nseg) - 1.
    q=''
    ;
    for j = 0, nseg-1 do begin
	;
	; get ID
	sno = sids[j]
	;
	; get costheta
	costh = cos(thetas[j])
	;
	; get x points
	t = where(seg eq sno,nt)
	if nt gt 0 then begin
		ind = array_indices(seg, t)
		xs = minmax(ind[0,*])
		nx = (xs[1] - xs[0]) + 1
		;
		; get larger muons within a certain angle
		if yrms[j] ge mw0 and yrms[j] le mw1 and costh ge 0.7 and $
	   	xrms[j] gt 9. then begin
			if keyword_set(verbose) then $
				print,'seg # '+strn(sno)+' passed'
			xx = indgen(nx) + xs[0]
			sg = fltarr(nx)
			;
			; loop over x points
			for i = 0, nx-1 do begin
				;
				; fit CR
				sig = muon_sample(im, seg, sno, xx[i], gplot=gplot)
				;
				; store results
				sg[i] = sig
			endfor
			g = where(xx gt 0 and sg gt 0., ng)
			if ng gt 0 then begin
				xx = xx[g]
				sg = sg[g]
				sgth = sg*costh
				coef = linfit(xx,sgth,/double,yfit=yfit)
				diff = sgth-yfit
				ims_asym,diff,md,sgd,wgt,siglim=[3.,2.]
				g = where(wgt eq 1)
				b = where(wgt ne 1,nb)
				coef = linfit(xx[g],sgth[g],/double)
				yfit = coef[0] + xx * coef[1]
				if keyword_set(crplot) then begin
				if sno eq crplot then begin
					psfile,'im08_cr'+strn(crplot)
					deepcolor
					!p.background=colordex('white')
					!p.color=colordex('black')
					!p.font=0
					th=5
					si=1.75
					plot,xx,sg,psym=-5,  $
						title='CR#: '+strn(sno), $
	xthick=th,xtitle='X (px)',xcharsi=si, $
	ythick=th,ytitle='!9s!3(px)',ycharsi=si,yran=[0.15,0.8],/ys, $
	charthi=th,charsi=si,/nodata
					oplot,xx,sgth,psym=-6
					oplot,xx,yfit,linesty=2,thick=5
					x = xx[g]
					oplot,[x[0],x[0]],!y.crange,linesty=3
					oplot,[x[-1],x[-1]],!y.crange,linesty=3
					oplot,!x.crange,[1./sqrt(12.),1./sqrt(12.)], $
						linesty=5
					xyouts,1305,0.3,'1/12!U1/2!N',charsi=si,$
						charthi=th
					xyouts,1284,0.2,'MAX',charsi=si, $
						charthi=th
					xyouts,1325,0.2,'MIN',charsi=si, $
						charthi=th
					if nb gt 0 then oplot,xx[b],sgth[b], $
								psym=2,symsi=2.
					psclose
					;read,'next: ',q
				endif
				endif
				;
				; store values
				mm = minmax(yfit[g])
				small[j] = mm[0]
				big[j] = mm[1]
				allsmall[p] = mm[0]
				allbig[p] = mm[1]
				p += 1
				;read,'next: ',q
			endif else print,'No good points'
		endif
    	endif else print,'Could not find segment '+strn(sno)
    endfor
    ;
    ; clean
    g = where(big gt 0, ng)
    big = big[g]
    small = small[g]
    print,imf+':  N CRs = '+strn(ng)
    ;
    ; final histo
    if keyword_set(hplot) then begin
    	plothist,big,bin=bs,xran=[0.,1.5], title=imf
    	plothist,small,bin=bs,/overplot,linesty=2
    	read,'next: ',q
    endif
;
; end loop over files
endfor
g = where(allbig gt 0, ng)
allbig = allbig[g]
allsmall = allsmall[g]
print,'N Crs: '+strn(ng)
diflen = sqrt(allbig*allbig - allsmall*allsmall) * 15.0
diflen2 = sqrt(allbig*allbig - 0.08333) * 15.0
mo = moment(diflen[where(diflen le 50)])
mo2 = moment(diflen2[where(diflen2 le 50)])
hd = histogram(diflen,bin=0.1,max=50.,loc=hx)
hd2 = histogram(diflen2,bin=0.1,max=50.,loc=hx2)
print,'mean diff  = '+string(mo[0],form='(f10.2)') + ' +- ' + $
	string(sqrt(mo[1]), form='(f10.2)')
print,'mean diff2 = '+string(mo2[0],form='(f10.2)') + ' +- ' + $
	string(sqrt(mo2[1]), form='(f10.2)')

if keyword_set(ps) then begin
	psfile,cwd+'_difflen'
	!p.font=0
endif
deepcolor
!p.background=colordex('white')
!p.color=colordex('black')
th=5
si=1.75

tlab = cwd + ' - ALL '+strn(nf)+' images, '+strn(ng)+' muon CRs'
plot,hx2,hd2,psym=10,title=tlab,xran=xlim,/xs, $
	xthick=th,xtitle='Diffusion Length (!9m!3-m)',xcharsi=si, $
	ythick=th,ytitle='N',ycharsi=si, $
	charthi=th,charsi=si
medl2 = median(diflen2)
oplot,[medl2,medl2],!y.crange
oplot,hx,hd,psym=10,linesty=2
medl = median(diflen)
oplot,[medl,medl],!y.crange,linesty=2
my_legend,['!9s!3!DMAX!N - !9s!3!DMIN!N', '!9s!3!DMAX!N - 1/12!U1/2!N'], $
	linesty=[2,0],charsi=1.25,charthi=th,box=0,spac=2.
print,'Median diffusion length (microns): ',medl,format='(a,f9.3)'
print,'Median diffusion length 2 (microns): ',medl2,format='(a,f9.3)'
;
if keyword_set(ps) then psclose
;
return
end