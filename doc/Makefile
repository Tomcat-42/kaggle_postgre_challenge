TEX      = pdflatex
BIB      = bibtex
FLAGS    = -interaction=nonstopmode -halt-on-error
SRCDIR   = src
BUILDDIR = build
OUT      = $(BUILDDIR)/main.pdf

.PHONY: all clean watch

all: $(OUT)

$(OUT): $(SRCDIR)/main.tex $(SRCDIR)/references.bib | $(BUILDDIR)
	cp $(SRCDIR)/*.tex $(SRCDIR)/*.bib $(BUILDDIR)/

	cd $(BUILDDIR) && $(TEX) $(FLAGS) main.tex
	-cd $(BUILDDIR) && $(BIB) main
	cd $(BUILDDIR) && $(TEX) $(FLAGS) main.tex
	cd $(BUILDDIR) && $(TEX) $(FLAGS) main.tex

$(BUILDDIR):
	mkdir -p $(BUILDDIR)

clean:
	rm -rf $(BUILDDIR)
	rm -f $(SRCDIR)/*.aux $(SRCDIR)/*.bbl $(SRCDIR)/*.blg $(SRCDIR)/*.log $(SRCDIR)/*.out $(SRCDIR)/*.fls $(SRCDIR)/*.fdb_latexmk $(SRCDIR)/*.synctex.gz $(SRCDIR)/*.pdf

watch:
	@echo "Watching $(SRCDIR)/ for changes..."
	@while true; do inotifywait -rqe modify $(SRCDIR)/main.tex $(SRCDIR)/references.bib && $(MAKE) all; done
