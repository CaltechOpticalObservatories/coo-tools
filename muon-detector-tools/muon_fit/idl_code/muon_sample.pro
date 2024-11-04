function muon_sample, im, seg, sno, x, pk, gplot=gplot
;+
; muon_sample - return y trace of muon
;-
yivec = reform(im[x, *])
ysvec = reform(seg[x, *])
;
; length of y vector
ny = n_elements(ysvec)
;
; find segment number in slice
svec = where(ysvec eq sno, nsvec)
;
; do we have enought data?
if nsvec gt 0 then begin
	;
	; extend beyond bottom and top
	y0 = (min(svec) - 5) > 0
	y1 = (max(svec) + 5) < (ny-1)
	nfit = (y1 - y0) + 1
	if nfit le 5 then begin
		sig = -1.
		pk = -1.
	endif else begin
		yf = yivec[y0:y1]
		xf = findgen(nfit)
		yfit = gaussfit(xf, yf, coef, nterm=4)
		sig = coef[2]
		pk = coef[0]
		if keyword_set(gplot) then begin
			q = ''
			plot,xf,yf-coef[3],psym=5, $
				title='Seg: '+strn(sno)+', x: '+strn(x)
			oplot,xf,yfit-coef[3]
			read,'next: ',q
		endif
	endelse
endif else begin
	sig = -1.
	pk = -1.
endelse
;
;
return, sig
end